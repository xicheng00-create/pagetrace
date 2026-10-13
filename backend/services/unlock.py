"""掌握度解锁（SCHED-001/002/006）：使用界面同源章级掌握度。"""
from __future__ import annotations

from config import BaseConfig
from flask import g

from services import cards as card_pool
from services.clock import now_iso
from services.mastery import level_mastery
from services.progress import _level_cards


def _uid(user_id=None):
    if user_id is not None:
        return user_id
    try:
        uid = getattr(g, "user_id", None)
    except RuntimeError:
        uid = None
    if uid is None:
        try:
            from flask import has_request_context
            if not has_request_context():
                return 1
        except RuntimeError:
            return 1
        raise RuntimeError("authenticated user required")
    return uid


def _thresholds(ratio=None, min_learned=None):
    return (BaseConfig.UNLOCK_MASTERY_RATIO if ratio is None else ratio,
            BaseConfig.UNLOCK_MIN_LEARNED if min_learned is None else min_learned)


def chapter_stats(con, chapter_id, at=None, user_id=None):
    uid = _uid(user_id)
    at = at or now_iso()
    row = card_pool.chapter_pool_counts(con, at, chapter_id, uid).fetchone()
    learned, mastered = row["learned"] or 0, row["mastered"] or 0
    return {"learned": learned, "mastered": mastered, "due": row["due"] or 0,
            "total": row["total"] or 0, "ratio": mastered / learned if learned else 0.0}


def _mastery(con, chapter_id, at, user_id=None):
    return level_mastery(_level_cards(con, chapter_id=chapter_id, at=at, user_id=user_id))


def is_ready(con, chapter_id, *, ratio=None, min_learned=None, at=None, user_id=None):
    uid = _uid(user_id)
    _, configured_min = _thresholds(ratio, min_learned)
    stats = chapter_stats(con, chapter_id, at, uid)
    required = min(configured_min, stats["total"])
    if stats["learned"] < required:
        return False, f"已学 {stats['learned']} < {required}（本章共 {stats['total']} 张）"
    mastery = _mastery(con, chapter_id, at or now_iso(), uid)
    if mastery["state"] != "master":
        return False, f"掌握度 {mastery.get('m') or 0}% < 80%"
    if stats["due"] > 0:
        return False, f"仍有 {stats['due']} 张到期未复习"
    return True, "达标"


def unlock_chapter(con, chapter_id, user_id=None):
    uid = _uid(user_id)
    row = con.execute("SELECT ch.unlocked_at FROM chapters ch JOIN books b ON b.id=ch.book_id WHERE ch.id=? AND b.owner_id=?", (chapter_id, uid)).fetchone()
    if row is None or row["unlocked_at"]:
        return False
    con.execute("UPDATE chapters SET unlocked_at=?,status='unlocked' WHERE id=?", (now_iso(), chapter_id))
    return True


def maybe_unlock(con, *, ratio=None, min_learned=None, at=None):
    uid = _uid()
    unlocked = []
    for book in con.execute("SELECT id FROM books WHERE owner_id=? ORDER BY id", (uid,)).fetchall():
        chapters = con.execute("SELECT id,unlocked_at FROM chapters WHERE book_id=? ORDER BY order_no,id", (book["id"],)).fetchall()
        if not chapters:
            continue
        if not chapters[0]["unlocked_at"] and unlock_chapter(con, chapters[0]["id"], uid):
            unlocked.append(chapters[0]["id"])
        for prev, cur in zip(chapters, chapters[1:], strict=False):
            if cur["unlocked_at"]:
                continue
            if not (prev["unlocked_at"] or prev["id"] in unlocked):
                break
            ready, _ = is_ready(con, prev["id"], ratio=ratio, min_learned=min_learned, at=at, user_id=uid)
            if not ready:
                break
            if unlock_chapter(con, cur["id"], uid):
                unlocked.append(cur["id"])
            else:
                break
    return unlocked
