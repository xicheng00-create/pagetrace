"""GET /api/cards — 卡片及后端掌握度。"""

from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, e_not_found, ok
from services import cards as card_pool
from services import labels
from services.nav import response_nav
from services.progress import card_metrics

bp = Blueprint("cards", __name__)


@bp.get("/api/cards")
def list_cards():
    cid = request.args.get("concept_id", type=int)
    if not cid:
        return e_input("缺少 concept_id")
    con = get_db()
    cp = con.execute(
        "SELECT cp.name FROM concepts cp JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id WHERE cp.id=? AND b.owner_id=?",
        (cid, g.user_id),
    ).fetchone()
    if cp is None:
        return e_not_found()
    concept_name = cp["name"]
    rows = card_pool.cards_for_concept(con, cid, g.user_id).fetchall()
    # CARD-007 / UI-019：`subtitle` = 子卡短名（后端唯一入口，前端零 split）；`concept_name` 供概念页标题用。
    cards = [
        {
            **dict(row),
            **labels.display_fields(dict(row), concept_name),
            "status_label": labels.status_label(row["status"]),
            "mastery": card_metrics(con, row["id"]),
        }
        for row in rows
    ]
    return ok({"nav": response_nav(con, "concept", cid, g.user_id), "concept_name": concept_name, "cards": cards})
