"""GET /api/quote — 首页每日格言（HOME-001）。

返回 `{id, text, total}`：`id` = 当天索引（同一自然日恒定，跨日 +1 模句数），
`text` = 格言正文（**无作者/出处字段，绝不编造署名**）；数据源为空 → `{id:null, text:"今日复习"}`。
"""
from flask import Blueprint
from middleware.errors import ok
from services import quotes

bp = Blueprint("quote", __name__)


@bp.get("/api/quote")
def quote():
    return ok(quotes.today_quote())
