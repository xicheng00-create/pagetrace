"""复习计划视图（PLAN-001）：列出**状态非 new** 的卡。**只读**，不写库、不另起调度。

口径（🔒 对后续一律适用）：
- 数据源 = `cards`（`status <> 'new'`）+ 章 / 书出处。
- 排序：**已到期（`next_review_at <= now`）在前** → 组内按 `next_review_at` **升序**；空值排最后。
- 间隔文案 `when_label` 一律由 `next_review_at` **机械换算**（后端单点）：
  `已到期` / `N 天后` / `N 小时后` / `N 分钟后`（< 1 小时）。
  前端**不得另算一套、不得写死**（断言同时锁后端换算式与前端引用 `when_label`）。
- 已到期的卡提供**直接作答**入口，作答复用复习卡路径（唯一调度 `review_sched.apply_result`）——
  本模块不参与作答，只提供计划数据。

时间口径：`next_review_at` 存东八区 ISO（`services.clock`），比较一律用同一时区 `now()`。
"""

from __future__ import annotations

from datetime import datetime

from flask import g

from services import cards as card_pool
from services import labels
from services.clock import TZ8, iso, now

_MINUTE, _HOUR, _DAY = 60, 3600, 86400


def when_label(next_iso: str | None, at: datetime | None = None) -> str:
    """把 `next_review_at` 机械换算为人类可读间隔（PLAN-001）。

    返回 `已到期` / `N 天后` / `N 小时后` / `N 分钟后`；空值或非法值 → `''`（不抛异常）。
    """
    if not next_iso:
        return ""
    at = at or now()
    try:
        nxt = datetime.fromisoformat(str(next_iso))
    except ValueError:
        return ""
    if nxt.tzinfo is None:  # 缺时区按本地时区解读（不应发生，防御式）
        nxt = nxt.replace(tzinfo=TZ8)
    secs = (nxt - at).total_seconds()
    if secs <= 0:
        return "已到期"
    if secs >= _DAY:
        return f"{int(secs // _DAY)} 天后"
    if secs >= _HOUR:
        return f"{int(secs // _HOUR)} 小时后"
    return f"{max(1, int(secs // _MINUTE))} 分钟后"


def plan_items(con, at: datetime | None = None) -> list[dict]:
    """状态非 new 的卡，已到期在前 → 下次复习时间升序。"""
    at = at or now()
    at_iso = iso(at)
    rows = card_pool.scheduled_plan_cards(con, at_iso, g.user_id).fetchall()
    out = []
    for r in rows:
        due = bool(r["next_review_at"] and r["next_review_at"] <= at_iso)
        out.append(
            {
                "card_id": r["card_id"],
                "front": r["front"],
                "status": r["status"],
                "status_label": labels.status_label(r["status"]),
                "book": r["book"],
                "chapter": r["chapter"],
                "concept": r["concept"],
                "title": r["title"],
                "subtitle": labels.subtitle_of(r["title"], r["concept"]),
                "source_label": labels.display_fields(dict(r))["source_label"],
                "next_review_at": r["next_review_at"],
                "due": due,
                "when_label": when_label(r["next_review_at"], at),
            }
        )
    return out
