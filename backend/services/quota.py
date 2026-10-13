"""UP-007：东八区自然月内已接收页数；前端只读后端文案。"""

from datetime import datetime

from config import BaseConfig
from flask import current_app, g, has_app_context, has_request_context

from services.clock import TZ8, now


def _uid(user_id=None):
    if user_id is not None:
        return user_id
    if not has_request_context():
        return 1
    return getattr(g, "user_id", None)


def quota_state(con, user_id=None):
    uid = _uid(user_id)
    if uid is None:
        raise ValueError("authenticated user required")
    at = now().astimezone(TZ8)
    limit = (
        current_app.config.get("UPLOAD_MONTHLY_PAGES", BaseConfig.UPLOAD_MONTHLY_PAGES)
        if has_app_context()
        else BaseConfig.UPLOAD_MONTHLY_PAGES
    )
    used = sum(
        row["pages"]
        for row in con.execute("SELECT pages,created_at FROM upload_jobs WHERE owner_id=?", (uid,))
        if datetime.fromisoformat(row["created_at"]).astimezone(TZ8).strftime("%Y-%m") == at.strftime("%Y-%m")
    )
    remaining = max(0, limit - used)
    enabled = has_app_context() and current_app.config.get("UPLOAD_WORKER_ENABLED", False)
    return {
        "can_upload": bool(enabled and remaining),
        "reason": (
            "本月上传额度已用完" if not remaining else "" if enabled else "上传处理尚未启用，暂不可用。"
        ),
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "label": f"本月已接收 {used} 页 · 剩余 {remaining} 页（额度 {limit} 页）",
    }


def check_quota(con, pages, user_id=None):
    state = quota_state(con, user_id)
    if pages > state["remaining"]:
        raise QuotaError(f"本月上传额度已用完（{state['limit']} 页）")
    return state


class QuotaError(ValueError):
    """配额错误与文件错误分开响应。"""
