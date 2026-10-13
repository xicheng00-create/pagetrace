"""图书复习范围，按用户隔离。"""

from __future__ import annotations

import json

from flask import g

from services.clock import now_iso
from services.mastery import level_mastery
from services.progress import _level_cards

KEY = "book_scope"


def _uid():
    uid = getattr(g, "user_id", None)
    if uid is None:
        raise RuntimeError("authenticated user required")
    return uid


def _read_book_scope(con):
    uid = _uid()
    row = con.execute("SELECT value FROM prefs WHERE user_id=? AND key=?", (uid, KEY)).fetchone()
    if row is None:
        return None, False
    try:
        ids = [int(x) for x in json.loads(row["value"] or "[]")]
    except (TypeError, ValueError):
        return None, False
    if not ids:
        con.execute("DELETE FROM prefs WHERE user_id=? AND key=?", (uid, KEY))
        return None, True
    return ids, False


def get_book_scope(con):
    return _read_book_scope(con)[0]


def set_book_scope(con, book_ids):
    uid = _uid()
    if book_ids is None:
        con.execute("DELETE FROM prefs WHERE user_id=? AND key=?", (uid, KEY))
        return
    con.execute(
        "INSERT INTO prefs(user_id,key,value) VALUES(?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
        (uid, KEY, json.dumps([int(x) for x in book_ids])),
    )


def book_filter(book_ids, column):
    if book_ids is None:
        return "", []
    if not book_ids:
        return " AND 0", []
    return f" AND {column} IN ({','.join('?' * len(book_ids))})", list(book_ids)


def scope_state(con):
    uid = _uid()
    at = now_iso()
    books = con.execute(
        "SELECT b.id,b.title,s.name AS subject,s.id AS subject_id FROM books b JOIN subjects s ON s.id=b.subject_id WHERE b.owner_id=? ORDER BY s.id,b.id",
        (uid,),
    ).fetchall()
    out = []
    for b in books:
        cards = _level_cards(
            con,
            book_id=b["id"],
            at=at,
        )
        m = level_mastery(cards)
        out.append(
            {
                "id": b["id"],
                "title": b["title"],
                "subject": b["subject"],
                "subject_id": b["subject_id"],
                "cards_total": m["cards_total"],
                "learned": m["learned"],
                "coverage": m["coverage"],
                "mastery": m,
            }
        )
    selected, repaired = _read_book_scope(con)
    return {
        "all": selected is None,
        "empty": False,
        "repaired": repaired,
        "selected_ids": None if selected is None else selected,
        "books": out,
        "label": _label(out, selected),
    }


def _label(books, selected):
    if selected is None:
        return "图书：全部"
    names = [b["title"] for b in books if b["id"] in set(selected)]
    return f"图书：{len(selected)}/{len(books)} 本（{'、'.join(names)}）"
