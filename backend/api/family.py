"""Family progress dashboard and private sharing preference."""
from datetime import timedelta

from auth import current_user_id
from data.db import get_db
from flask import Blueprint, request
from middleware.errors import e_input, err, ok
from services.cards import household_coverage_counts
from services.clock import now
from services.household import my_household

bp = Blueprint("family", __name__)


def _metrics(con, household_id, user_id):
    today = con.execute("SELECT COUNT(DISTINCT card_id) FROM card_reviews WHERE user_id=? AND date(learned_at)=date('now','localtime')", (user_id,)).fetchone()[0]
    counts = household_coverage_counts(con, user_id).fetchone()
    last = con.execute("SELECT MAX(learned_at) FROM card_reviews WHERE user_id=?", (user_id,)).fetchone()[0]
    days = {r[0] for r in con.execute("SELECT DISTINCT date(learned_at) FROM card_reviews WHERE user_id=?", (user_id,))}
    cursor = now().date()
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= timedelta(days=1)
    return {"today_cards": today, "coverage": round((counts["learned"] or 0) * 100 / counts["total"]) if counts["total"] else 0, "streak": streak, "last_active": last}


@bp.get("/api/family")
def family():
    con = get_db()
    uid = current_user_id()
    household = my_household(con, uid)
    me = con.execute("SELECT id,username,share_progress FROM users WHERE id=?", (uid,)).fetchone()
    members = []
    for user in con.execute("SELECT id,username,role,share_progress FROM users WHERE household_id=? ORDER BY id", (household["id"],)):
        shared = bool(user["share_progress"])
        if user["id"] == uid:
            item = {"id": user["id"], "username": user["username"], "role": user["role"], "shared": shared}
            item.update(_metrics(con, household["id"], user["id"]))
        elif shared:
            item = {"id": user["id"], "username": user["username"], "role": user["role"], "shared": True}
            item.update(_metrics(con, household["id"], user["id"]))
        else:
            item = {"id": user["id"], "username": user["username"], "shared": False}
        members.append(item)
    return ok({"household": {"id": household["id"], "name": household["name"]}, "me": {"id": uid, "shared": bool(me["share_progress"])}, "members": members})


@bp.post("/api/family/share")
def share():
    data = request.get_json(silent=True) or {}
    value = data.get("shared")
    if type(value) is not bool:
        return e_input("shared 必须为布尔值")
    con = get_db()
    con.execute("UPDATE users SET share_progress=? WHERE id=?", (int(value), current_user_id()))
    con.commit()
    return ok({"shared": value})


@bp.get("/api/family/member/<int:member_id>")
def member_detail(member_id):
    """小组成员钻取页：点成员头像看 TA 的进度（仅同户且本人允许展示）。"""
    con = get_db()
    uid = current_user_id()
    household = my_household(con, uid)
    user = con.execute("SELECT id,username,role,share_progress,household_id FROM users WHERE id=?", (member_id,)).fetchone()
    if not user or user["household_id"] != household["id"]:
        return err("NOT_FOUND", "成员不存在", 404)
    if user["id"] != uid and not user["share_progress"]:
        return err("FORBIDDEN", "该成员未公开进度", 403)
    data = {"id": user["id"], "username": user["username"], "role": user["role"], "is_me": user["id"] == uid}
    data.update(_metrics(con, household["id"], user["id"]))
    data.update(_today_three(con, user["id"]))
    data["recent"] = [
        {"day": r[0], "cards": r[1]}
        for r in con.execute(
            "SELECT date(learned_at) d, COUNT(DISTINCT card_id) FROM card_reviews WHERE user_id=? "
            "GROUP BY d ORDER BY d DESC LIMIT 7", (user["id"],)
        )
    ]
    return ok(data)


def _today_three(con, user_id):
    """今日三项：视频 N / 卡片 N / 刷题 N（与连胜口径同源）。"""
    from services.tasks import today_task
    task = today_task(con, user_id=user_id)
    return {
        "today": {
            "video": task["video"],
            "review": {"target": task["review"]["target"], "done": task["review"]["done"]},
            "quiz": {"target": task["quiz"]["target"], "done": task["quiz"]["done"]},
        }
    }
