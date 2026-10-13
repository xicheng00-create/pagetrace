"""GET /api/progress — 每科**汇总**进度（DATA-004 / DATA-005）。

学科级只给汇总（本书/章数/已学 x / 共 y 张），**不给**「解锁到第几章」这类单值；
书的解锁进度是书的属性，见 GET /api/books（逐书取值）。
"""
from data.db import get_db
from flask import Blueprint
from middleware.errors import ok
from services.progress import subject_metrics

bp = Blueprint("progress", __name__)


@bp.get("/api/progress")
def progress():
    return ok({"subjects": subject_metrics(get_db())})
