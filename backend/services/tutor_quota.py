"""tutor 每日配额（规格 v0.1 §5）：user × 东八区自然日计数，超限 429 + 固定文案。

上限只从配置来（`TUTOR_DAILY_LIMIT`，默认 40），代码里不写死数字。
计数口径 = 调用次数（不含缓存命中）；用量的 token 记账与 messages 同源，缺数字记 NULL 而非 0。
"""
from __future__ import annotations

from config import BaseConfig
from flask import current_app, has_app_context

from services.clock import TZ8, now

MESSAGE = "今天的 tutor 次数用完了，明天再来"


class TutorQuotaError(RuntimeError):
    """当日次数用尽（API 层转 429）。"""


def limit() -> int:
    value = (current_app.config.get("TUTOR_DAILY_LIMIT", BaseConfig.TUTOR_DAILY_LIMIT)
             if has_app_context() else BaseConfig.TUTOR_DAILY_LIMIT)
    return max(int(value), 0)


def day() -> str:
    return now().astimezone(TZ8).date().isoformat()


def _used(con, user_id, today) -> int:
    row = con.execute(
        "SELECT chat_calls FROM quota_usage WHERE user_id=? AND day=?", (user_id, today)
    ).fetchone()
    return int(row[0]) if row else 0


def state(con, user_id) -> dict:
    today, cap, used = day(), limit(), 0
    used = _used(con, user_id, today)
    remaining = max(cap - used, 0)
    return {
        "day": today,
        "limit": cap,
        "used": used,
        "remaining": remaining,
        "label": f"今天已用 {used} / {cap} 次",
    }


def consume(con, user_id) -> dict:
    """记一次调用；已用满则抛 TutorQuotaError（此时不写库，配额不因被拒而虚增）。"""
    today = day()
    used = _used(con, user_id, today)
    if used >= limit():
        raise TutorQuotaError(MESSAGE)
    con.execute(
        "INSERT INTO quota_usage(user_id,day,chat_calls,tokens_in,tokens_out) VALUES(?,?,1,0,0)"
        " ON CONFLICT(user_id,day) DO UPDATE SET chat_calls=chat_calls+1",
        (user_id, today),
    )
    return state(con, user_id)


def add_tokens(con, user_id, tokens_in, tokens_out) -> None:
    """累计本次 token 用量；未知（None）不计，保持 NULL 语义不落假 0。"""
    if not tokens_in and not tokens_out:
        return
    con.execute(
        "UPDATE quota_usage SET tokens_in=tokens_in+?, tokens_out=tokens_out+?"
        " WHERE user_id=? AND day=?",
        (tokens_in or 0, tokens_out or 0, user_id, day()),
    )
