"""GET /api/chapters?book_id= — 某书的章（钻取第 3 级）+ 未解锁原因（UI-003）。

章级掌握度（MAST-001）：分子 = 该章 mastered 卡数、分母 = 该章已学卡数（`status<>'new'`）；
分母 0 → pct 0 且 started false（不除零），由 `services.progress.mastery` 单点算。
"""
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, ok
from services import unlock
from services.clock import now_iso
from services.mastery import level_mastery
from services.nav import response_nav
from services.progress import _level_cards

VISIBLE_BOOK_SQL = (
    "b.owner_id IN (SELECT u2.id FROM users u2 "
    "WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))"
)

bp = Blueprint("chapters", __name__)


@bp.get("/api/chapters")
def list_chapters():
    bid = request.args.get("book_id", type=int)
    if not bid:
        return e_input("缺少 book_id")
    con = get_db()
    visibility, visibility_params = VISIBLE_BOOK_SQL, [g.user_id]
    book = con.execute(f"SELECT id FROM books b WHERE id=? AND {visibility}", (bid, *visibility_params)).fetchone()
    if book is None:
        from middleware.errors import e_not_found
        return e_not_found()
    rows = con.execute(
        "SELECT id, name, anchor, order_no, unlocked_at, status FROM chapters"
        " WHERE book_id=? ORDER BY order_no, id", (bid,)).fetchall()
    out, prev_id = [], None
    for r in rows:
        stats = unlock.chapter_stats(con, r["id"])
        if r["unlocked_at"]:
            reason = None
        elif prev_id is None:
            reason = "本章暂无卡入库（入库即解锁）"
        else:
            _ok, why = unlock.is_ready(con, prev_id)
            reason = f"上一章未达标：{why}"
        chapter_mastery = level_mastery(_level_cards(con, chapter_id=r["id"], at=now_iso()))
        out.append({**dict(r), "unlocked": bool(r["unlocked_at"]), "lock_reason": reason,
                    "cards_total": stats["total"], "learned": stats["learned"],
                    "mastered": stats["mastered"], "due": stats["due"], "mastery": chapter_mastery})
        prev_id = r["id"]
    return ok({"nav": response_nav(con, "book", bid, g.user_id), "chapters": out})
