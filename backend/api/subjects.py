"""GET /api/subjects — 学科列表（含 DATA-004 四个数）。"""
from data.db import get_db
from flask import Blueprint
from middleware.errors import ok
from services.progress import subject_metrics

bp = Blueprint("subjects", __name__)


@bp.get("/api/subjects")
def list_subjects():
    return ok({"subjects": subject_metrics(get_db())})
