"""GET /api/concepts?chapter_id= — 某章的概念（钻取第 4 级）。未解锁 → 返回原因，不泄露内容。

MAST-005（v0.6.1）：每个概念项带**后端算好**的两个字段 ——
- `status_counts`：`{new, learning, reviewing, mastered}`（**恒四键**，缺省 0）；
- `status_label`：**全部同态** → 该态中文标签；**多态** → `未学习 2 · 学习中 1`
  （顺序固定 新→学→复→掌，**只列非零项**）；**无卡** → `无卡`。

词表唯一来源 = `config.BaseConfig.STATUS_LABELS`（前端零映射、零拼接）。
未知 `status` → 计入 `new`，并在响应 `warnings` 追加一条 + 记 log（不许静默吞）。
"""
import logging

from config import BaseConfig
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, e_not_found, ok
from services import cards as card_pool
from services import unlock
from services.nav import response_nav

bp = Blueprint("concepts", __name__)
logger = logging.getLogger(__name__)

_KEYS = BaseConfig.STATUS_ORDER


def _empty_counts() -> dict:
    return {k: 0 for k in _KEYS}


def format_status_label(counts: dict) -> str:
    """同态 → 该态中文；多态 → `未学习 2 · 学习中 1`（顺序固定、只列非零）；无卡 → 「无卡」。"""
    nonzero = [(k, counts.get(k) or 0) for k in _KEYS if counts.get(k)]
    if not nonzero:
        return BaseConfig.STATUS_NO_CARD_LABEL
    if len(nonzero) == 1:
        return BaseConfig.STATUS_LABELS[nonzero[0][0]]
    return " · ".join(f"{BaseConfig.STATUS_LABELS[k]} {n}" for k, n in nonzero)


def _counts_by_concept(con, chid: int, warnings: list) -> dict:
    """按概念聚合四态计数；未知 status 计入 `new` 并记 warning（MAST-005）。"""
    rows = card_pool.concept_status_counts(con, chid, g.user_id).fetchall()
    per: dict[int, dict] = {}
    for r in rows:
        raw = r["status"]
        known = raw in BaseConfig.STATUS_LABELS
        if not known:
            msg = (f"概念 {r['concept_id']} 出现未知卡片状态 {raw!r}"
                   f" → 计入「{BaseConfig.STATUS_UNKNOWN_LABEL}」（MAST-005）")
            logger.warning(msg)
            warnings.append(msg)
        per.setdefault(r["concept_id"], _empty_counts())[raw if known else "new"] += r["n"]
    return per


@bp.get("/api/concepts")
def list_concepts():
    chid = request.args.get("chapter_id", type=int)
    if not chid:
        return e_input("缺少 chapter_id")
    con = get_db()
    ch = con.execute("SELECT ch.unlocked_at FROM chapters ch JOIN books b ON b.id=ch.book_id WHERE ch.id=? AND b.owner_id=?", (chid, g.user_id)).fetchone()
    nav = response_nav(con, "chapter", chid, g.user_id) if ch else {"parent_href": None, "parent_label": None}
    if ch is None:
        return e_not_found()
    if not ch["unlocked_at"]:
        _ok, why = unlock.is_ready(con, chid)
        return ok({"nav": nav, "locked": True, "reason": f"本章未解锁：{why}", "concepts": []})
    warnings: list[str] = []
    rows = card_pool.concepts_with_card_counts(con, chid, g.user_id).fetchall()
    per = _counts_by_concept(con, chid, warnings)
    concepts = []
    for r in rows:
        d = dict(r)
        counts = per.get(r["id"]) or _empty_counts()
        d["status_counts"] = counts
        d["status_label"] = format_status_label(counts)
        concepts.append(d)
    return ok({"nav": nav, "locked": False, "concepts": concepts, "warnings": warnings})
