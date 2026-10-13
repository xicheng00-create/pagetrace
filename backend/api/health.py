"""健康检查：/health → {status, version, db, contract_version, env}。

冒烟门禁（make smoke / CI）与上线验收都打这个端点，字段只许增不许改名。
"""
from data.db import get_db
from flask import Blueprint, current_app
from middleware.errors import ok

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    db_state = "ok"
    try:
        con = get_db()
        con.execute("SELECT 1").fetchone()
    except Exception as exc:  # noqa: BLE001 —— 健康检查必须永远 200，错误只体现在字段里
        db_state = f"error: {type(exc).__name__}"

    return ok(
        {
            "status": "ok",
            "version": current_app.config.get("VERSION"),
            "db": db_state,
            "contract_version": current_app.config.get("CONTRACT_VERSION"),
            "env": current_app.config.get("ENV", "unknown"),
        }
    )
