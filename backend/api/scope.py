
"""图书复习范围（SCOPE-001~003）：按租户读取/写入范围。"""
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, e_not_found, ok
from services import scope

bp = Blueprint("scope", __name__)


@bp.get("/api/scope")
def get_scope():
    return ok(scope.scope_state(get_db()))


@bp.put("/api/scope")
def set_scope():
    body = request.get_json(silent=True) or {}
    con = get_db()
    uid = g.user_id
    if body.get("all") is True:
        scope.set_book_scope(con, None)
    else:
        ids = body.get("book_ids")
        if ids is None:
            return e_input("缺少 book_ids 或 all")
        if not isinstance(ids, list):
            return e_input("book_ids 必须为数组")
        if any(not isinstance(i, int) or isinstance(i, bool) or i <= 0 for i in ids):
            return e_input("book_ids 元素必须为正整数")
        if not ids:
            return e_input("至少选择一本书")
        marks = ",".join("?" * len(ids))
        if con.execute(
            f"SELECT COUNT(*) FROM books WHERE owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) AND id IN ({marks})", [uid, *ids]
        ).fetchone()[0] != len(set(ids)):
            return e_not_found("存在不存在的书 id")
        scope.set_book_scope(con, ids)
    con.commit()
    return ok(scope.scope_state(con))
