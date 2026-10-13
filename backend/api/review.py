"""复习（REVIEW-002/003 / GOAL-001 / MAST-003）：GET /api/today 今日队列；POST /api/review/<id>。

今日队列 = 到期优先 + 未学新卡补齐（只取已解锁章），合计 = `min(target, 可用)`，
口径见 services/queue.today_queue（`extra=1` 为「再来一组」，同口径）。
响应字段只增不改名：due/count/batch_max 保持既有语义（count = due + new 总数），新增 new 分组；
每张卡新增 `status_label`（MAST-003，唯一词表，标签只在后端算）。
每次更新后顺带评估解锁（SCHED-001），故响应带 unlocked。
"""

from data.db import get_db
from flask import Blueprint, current_app, g, request
from middleware.errors import e_input, e_not_found, ok
from services import labels, queue, review_sched, scope, streak, unlock

bp = Blueprint("review", __name__)


def _label_cards(cards: list) -> list:
    """给队列里的每张卡补上后端算好的 `status_label`（MAST-003）与 `subtitle`（CARD-007/UI-019）。"""
    return [
        {**c, "status_label": labels.status_label(c.get("status")), **labels.display_fields(c)} for c in cards
    ]


@bp.get("/api/today")
def today():
    con = get_db()
    target = current_app.config.get("REVIEW_TASK_TARGET", 30)
    extra = request.args.get("extra") in ("1", "true", "yes")
    q = queue.today_queue(
        con,
        target=target,
        extra=extra,
        batch_max=current_app.config.get("REVIEW_BATCH_MAX", 100),
        new_max=current_app.config.get("NEW_CARDS_BATCH_MAX", 30),
        book_ids=scope.get_book_scope(con),
        user_id=g.user_id,
    )
    due, new = _label_cards(q["due"]), _label_cards(q["new"])
    return ok(
        {
            "due": due,
            "new": new,
            "count": len(due) + len(new),
            "batch_max": current_app.config.get("REVIEW_BATCH_MAX", 100),
            "group": q["group"],
        }
    )


@bp.post("/api/review/<int:card_id>")
def submit_review(card_id: int):
    body = request.get_json(silent=True) or {}
    result = body.get("result")
    if result not in review_sched.GRADES:
        return e_input("result 必须为 again/hard/good 之一")
    con = get_db()
    state = review_sched.apply_result(con, card_id, result)
    if state is None:
        return e_not_found("卡不存在")
    unlocked = unlock.maybe_unlock(con)
    con.commit()
    streak.record_day(con)
    return ok({"card": state, "unlocked": unlocked})
