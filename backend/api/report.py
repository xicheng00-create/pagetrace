"""GET /api/report — 本周概况（RPT-001）。**只读**。

统计窗口 = **本周一 00:00（本地时区）起**。返回：
`{week_start, reviewed_cards, quiz_answered, quiz_correct, accuracy, weakest_chapter}`。
- `accuracy` = 判对 ÷ 已作答（QUIZ-005 同一函数）；**0 作答 → null**（前端显 `—`，不显 0%）。
- `weakest_chapter` = 同 WEAK-001 口径的窗口内最弱一章（无错题 → null）。
"""
from data.db import get_db
from flask import Blueprint
from middleware.errors import ok
from services import report as report_svc

bp = Blueprint("report", __name__)


@bp.get("/api/report")
def report():
    return ok(report_svc.weekly_report(get_db()))
