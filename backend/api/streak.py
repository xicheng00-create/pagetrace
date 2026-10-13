"""GET /api/streak：返回连胜天数与今日目标达成状态。"""
from data.db import get_db
from flask import Blueprint
from middleware.errors import ok
from services import streak as streak_svc

bp = Blueprint("streak", __name__)


@bp.get("/api/streak")
def streak():
    con = get_db()
    return ok(streak_svc.compute(con))
