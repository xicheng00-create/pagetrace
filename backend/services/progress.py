"""层级进度：仅基于当前用户归属数据生成统计。"""

from __future__ import annotations

from datetime import datetime

from flask import g

from services import cards as card_pool
from services.clock import now_iso
from services.mastery import card_mastery, level_mastery


def _uid():
    value = getattr(g, "user_id", None)
    if value is None:
        raise RuntimeError("authenticated user required")
    return value


def _events(con, card_id, user_id=None):
    uid = user_id if user_id is not None else _uid()
    return [
        dict(earned=int(r[0]), created_at=r[1], points=r[2])
        for r in con.execute(
            "SELECT CASE WHEN result='good' THEN 1 ELSE 0 END,learned_at,1 FROM card_reviews WHERE card_id=? AND user_id=? UNION ALL SELECT qa.is_correct,qa.created_at,COALESCE(qi.points,1) FROM quiz_attempts qa JOIN quiz_items qi ON qi.id=qa.item_id WHERE qa.card_id=? AND qa.user_id=?",
            (card_id, uid, card_id, uid),
        ).fetchall()
    ]


def card_metrics(con, card_id, *, at=None, user_id=None):
    uid = user_id if user_id is not None else _uid()
    row = card_pool.card_status(con, card_id, uid).fetchone()
    if row is None:
        return {"m": 0, "acc": None, "evidence": False}
    return card_mastery(row["status"], _events(con, card_id, uid), at=at)


def _level_cards(con, *, at, user_id=None, book_id=None, chapter_id=None, subject_id=None):
    uid = user_id if user_id is not None else _uid()
    rows = card_pool.level_card_statuses(con, uid, book_id=book_id, chapter_id=chapter_id, subject_id=subject_id).fetchall()
    return [{"status": r["status"], "mastery": card_metrics(con, r["id"], at=at, user_id=uid)} for r in rows]


def subject_metrics(con, at=None):
    uid = _uid()
    at = at or now_iso()
    subjects = con.execute(
        "SELECT DISTINCT s.id,s.name,s.slug,s.order_no FROM subjects s JOIN books b ON b.subject_id=s.id WHERE b.owner_id=? ORDER BY s.order_no,s.id",
        (uid,),
    ).fetchall()
    out = []
    for s in subjects:
        cards = _level_cards(
            con,
            subject_id=s["id"],
            at=at,
        )
        stats = card_pool.subject_pool_counts(con, at, s, uid).fetchone()
        books = con.execute(
            "SELECT COUNT(*) FROM books WHERE subject_id=? AND owner_id=?", (s["id"], uid)
        ).fetchone()[0]
        chapters = con.execute(
            "SELECT COUNT(*) FROM chapters ch JOIN books b ON b.id=ch.book_id WHERE b.subject_id=? AND b.owner_id=?",
            (s["id"], uid),
        ).fetchone()[0]
        unlocked = con.execute(
            "SELECT COUNT(*) FROM chapters ch JOIN books b ON b.id=ch.book_id WHERE b.subject_id=? AND b.owner_id=? AND ch.unlocked_at IS NOT NULL",
            (s["id"], uid),
        ).fetchone()[0]
        last = card_pool.subject_last_review(con, s, uid).fetchone()[0]
        m = level_mastery(cards)
        out.append(
            {
                "id": s["id"],
                "name": s["name"],
                "slug": s["slug"],
                "books_total": books,
                "chapters_total": chapters,
                "chapters_unlocked": unlocked,
                "cards_total": stats["total"] or 0,
                "unlearned": stats["unlearned"] or 0,
                "due": stats["due"] or 0,
                "mastered": sum(c["status"] == "mastered" for c in cards),
                "learned": m["learned"],
                "mastery": m,
                "last_touch_at": last,
                "days_since_touch": _days_since(last, at),
            }
        )
    return out


def _days_since(ts, at):
    if not ts:
        return None
    try:
        return max((datetime.fromisoformat(at) - datetime.fromisoformat(ts)).days, 0)
    except ValueError:
        return None
