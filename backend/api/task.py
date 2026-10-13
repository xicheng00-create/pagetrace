"""GET /api/task — 今日任务清单（TASK-001 / GOAL-001）。

返回 `{review:{target,done,complete,reason}, quiz:{target,done,complete}, done}`：
- `review.target` = `min(REVIEW_TASK_TARGET, 今日可复习总数)`（一天内稳定）；`review.done` = 今日已复习卡数；
  `review.reason` = 退化态（可复习总数为 0）时的非空中文原因，供 UI-003 置灰文案。
- `quiz.target` = 今日测验目标题数（配置化）；`quiz.done` = 今日已作答题数（按题去重）。
- 只读；**不含任何催学文案/接口**（OPS-004 / SCHED-003），连胜仍由 /api/streak 独立提供。
"""
from data.db import get_db
from flask import Blueprint
from middleware.errors import ok
from services import scope, streak, tasks

bp = Blueprint("task", __name__)


@bp.get("/api/task")
def task():
    con = get_db()
    # Read path snapshot: tasks remains pure and streak is the sole persistence point.
    # 连胜快照按「全量目标」记（STREAK-004 保留），今日任务计数按「图书范围」下发（SCOPE-002）。
    streak.record_day(con)
    return ok(tasks.today_task(con, book_ids=scope.get_book_scope(con)))
