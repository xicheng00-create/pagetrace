"""GET /api/plan — 复习计划视图（PLAN-001）。**只读**。

返回 `{items:[{card_id,front,status,book,chapter,concept,next_review_at,due,when_label}]}`：
- 状态非 new 的卡，已到期在前 → 下次复习时间升序。
- 间隔文案 `when_label` 由后端按 `next_review_at` 机械换算（前端不得另算）。
- 已到期（`due=true`）的卡前端给**直接作答**入口（复用复习卡路径，唯一调度）。
"""
from data.db import get_db
from flask import Blueprint
from middleware.errors import ok
from services import plan as plan_svc

bp = Blueprint("plan", __name__)


@bp.get("/api/plan")
def plan():
    return ok({"items": plan_svc.plan_items(get_db())})
