"""复习调度（REVIEW-001）：唯一一套间隔算法，只认 learn_count/status/next_review_at。

三档结果（SM-2 派生，阈值/间隔全从 config 读）：
- again（不会）：status→learning，间隔 = AGAIN_INTERVAL_MINUTES 分钟，learn_count 不增长
- hard （模糊）：learn_count+1，status→reviewing，间隔 = HARD_INTERVAL_HOURS 小时
- good （会）  ：learn_count+1，间隔 = REVIEW_INTERVALS_DAYS[learn_count]，
                 learn_count ≥ MASTER_MIN_LEARN → status→mastered
掌握度只由 status='mastered' 决定；解锁单向（SCHED-002），回落不重新上锁。
"""
from __future__ import annotations

from datetime import timedelta

from config import BaseConfig
from flask import g, has_request_context

from services import cards as card_pool
from services.clock import iso, now

GRADES = ("again", "hard", "good")
STATUSES = ("new", "learning", "reviewing", "mastered")


def _good_days(learn_count: int) -> int:
    table = BaseConfig.REVIEW_INTERVALS_DAYS
    idx = min(max(learn_count, 1), len(table)) - 1
    return table[idx]


def compute(card: dict, result: str, at=None):
    """返回 (status, learn_count, next_review_at_iso)。纯函数，便于测试。"""
    if result not in GRADES:
        raise ValueError(f"非法结果 {result!r}")
    at = at or now()
    lc = int(card.get("learn_count") or 0)
    if result == "again":
        return "learning", lc, iso(at + timedelta(minutes=BaseConfig.AGAIN_INTERVAL_MINUTES))
    if result == "hard":
        lc += 1
        return "reviewing", lc, iso(at + timedelta(hours=BaseConfig.HARD_INTERVAL_HOURS))
    # good
    lc += 1
    status = "mastered" if lc >= BaseConfig.MASTER_MIN_LEARN else "reviewing"
    return status, lc, iso(at + timedelta(days=_good_days(lc)))


def apply_result(con, card_id: int, result: str, at=None, user_id=None) -> dict | None:
    """落库：写 card_reviews 历史 + 更新 cards 当前状态。card 不存在 → None。

    返回值含 `review_id`（本次写入的 card_reviews 行 id），供调用方做幂等替换
    （出题自测重复作答时删旧行、写新行，避免重复历史）。
    """
    if result not in GRADES:
        raise ValueError(f"非法结果 {result!r}")
    uid = user_id
    if uid is None and has_request_context():
        uid = getattr(g, "user_id", None)
    if uid is None:
        raise RuntimeError("authenticated user required")
    row = card_pool.card_schedule(con, card_id, uid).fetchone()
    if row is None:
        return None
    status, lc, nxt = compute(dict(row), result, at)
    when = iso(at or now())
    cur = con.execute(
        "INSERT INTO card_reviews(card_id, learned_at, result, next_review_at, learn_count, status, user_id)"
        " VALUES(?,?,?,?,?,?,?)", (card_id, when, result, nxt, lc, status, uid))
    card_pool.update_card_schedule(con, card_id, lc, nxt, status, uid)
    return {"card_id": card_id, "status": status, "learn_count": lc,
            "next_review_at": nxt, "review_id": cur.lastrowid}
