"""GET /api/weak — 薄弱点页（WEAK-001）。**只读**。

返回 `{chapters:[{chapter_id,chapter,book,subject,wrong_count,card_count,cards:[...]}]}`：
- **按章聚合**（与错题本按卡不同）；**只出现有错题的章**；**按错次降序**。
- 数据源 = `quiz_attempts(is_correct=0)` → 卡 → 章；章内含涉及卡与各自错次。
"""
from data.db import get_db
from flask import Blueprint
from middleware.errors import ok
from services import report as report_svc

bp = Blueprint("weak", __name__)


@bp.get("/api/weak")
def weak():
    return ok({"chapters": report_svc.weak_chapters(get_db())})
