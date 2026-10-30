"""账号管理（REQ-ACCT-01）：看自己的进度、改密码。

个人维度只看本人：覆盖率/连胜/今日三项都由当前登录用户解析，不接受外部 user_id。
"""

from auth import password_hash, verify_password
from data.db import get_db
from flask import Blueprint, g, jsonify, request

bp = Blueprint("account", __name__)


def _progress(con, uid):
    from services.cards import household_coverage_counts
    from services.streak import compute
    from services.tasks import today_task

    row = household_coverage_counts(con, uid).fetchone()
    total = (row["total"] if row else 0) or 0
    learned = (row["learned"] if row else 0) or 0
    task = today_task(con, user_id=uid)
    try:
        streak_days = compute(con)["days"]
    except Exception:  # 读路径不得因连胜快照写库失败而 500
        streak_days = 0
    return {
        "coverage": learned * 100 // max(total, 1),
        "streak": streak_days,
        "today": {
            "video": task["video"],
            "review": {"target": task["review"]["target"], "done": task["review"]["done"]},
            "quiz": {"target": task["quiz"]["target"], "done": task["quiz"]["done"]},
            "done": task["done"],
        },
    }


@bp.get("/api/account")
def account():
    uid = g.user_id
    con = get_db()
    row = con.execute(
        "SELECT u.id,u.username,u.role,u.created_at,u.share_progress,h.name AS household_name "
        "FROM users u LEFT JOIN households h ON h.id=u.household_id WHERE u.id=?",
        (uid,),
    ).fetchone()
    if not row:
        return jsonify({"code": 401, "msg": "需要登录"}), 401
    data = {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "created_at": row["created_at"],
        "shared": bool(row["share_progress"]),
        "household": row["household_name"] or "我的小组",
    }
    data.update(_progress(con, uid))
    return jsonify({"code": 0, "data": data})


@bp.post("/api/account/password")
def change_password():
    uid = g.user_id
    body = request.get_json(silent=True) or {}
    current = (body.get("current_password") or "").strip()
    new = (body.get("new_password") or "").strip()
    if len(new) < 8:
        return jsonify({"code": 400, "msg": "新密码至少 8 位"}), 400
    if new == current:
        return jsonify({"code": 400, "msg": "新密码不能与旧密码相同"}), 400
    con = get_db()
    row = con.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
    if not row or not verify_password(current, row["password_hash"]):
        return jsonify({"code": 400, "msg": "当前密码不正确"}), 400
    con.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(new), uid))
    con.commit()
    return jsonify({"code": 0, "data": {"changed": True}})
