"""GET /api/books?subject_id= — 某学科下的书（钻取第 2 级）。

书级掌握度（MAST-001）：分子 = 该书 `status='mastered'` 卡数、分母 = 该书已学卡数
（`status<>'new'`）；分母 0 → pct 0 且 started false（不除零），由 `services.progress.mastery` 单点算。
`unlocked_upto` / `chapters_total` 是**书的属性**（逐书取值，UI-005/DATA-005）。
"""
from auth import current_user_id
from data.db import get_db
from flask import Blueprint, request
from middleware.errors import e_input, ok
from services import cards as card_pool
from services.clock import now_iso
from services.mastery import level_mastery
from services.nav import response_nav
from services.progress import _level_cards

bp = Blueprint("books", __name__)


@bp.get("/api/books")
def list_books():
    sid = request.args.get("subject_id", type=int)
    if not sid:
        return e_input("缺少 subject_id")
    con = get_db()
    rows = card_pool.books_with_pool_counts(con, sid, current_user_id()).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        cards = _level_cards(con, book_id=r["id"], at=now_iso())
        d["mastery"] = level_mastery(cards)
        out.append(d)
    return ok({"nav": response_nav(con, "subject", sid, current_user_id()), "books": out})
