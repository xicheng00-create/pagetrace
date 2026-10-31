from flask import g, has_request_context

from services.clock import now_iso

STAGE_LABELS = {
    "queued": "排队中",
    "extracting": "读取 PDF 文字",
    "segmenting": "按章切书",
    "cardgen": "生成知识卡片",
    "gated": "校验卡片",
    "ready": "草稿已就绪",
    "failed": "处理失败",
}

NEXT = {
    "queued": {"extracting", "failed"},
    "extracting": {"segmenting", "failed"},
    "segmenting": {"cardgen", "failed"},
    "cardgen": {"gated", "failed"},
    "gated": {"ready", "failed"},
    "ready": set(),
    "failed": {"queued"},
}


def _uid(user_id=None):
    if user_id is not None:
        return user_id
    return getattr(g, "user_id", None) if has_request_context() else None


def transition(con, job_id, status, progress, error=None, user_id=None):
    uid = _uid(user_id)
    if uid is None:
        raise ValueError("authenticated user required")
    row = con.execute("SELECT status FROM upload_jobs WHERE id=? AND owner_id=?", (job_id, uid)).fetchone()
    if row is None or status not in NEXT.get(row["status"], set()):
        raise ValueError("非法任务状态跳转")
    if not isinstance(progress, int) or not 0 <= progress <= 100:
        raise ValueError("进度必须为 0 至 100 的整数")
    cur = con.execute(
        "UPDATE upload_jobs SET status=?,stage=?,progress=?,error=?,updated_at=? "
        "WHERE id=? AND status=? AND owner_id=?",
        (status, status, progress, error, now_iso(), job_id, row["status"], uid),
    )
    if cur.rowcount != 1:
        raise ValueError("任务状态已变化，请重试")
    con.commit()


def set_progress(con, job_id, progress, user_id):
    """块级进度：阶段不变，只推进百分比（供前端估时）。"""
    uid = _uid(user_id)
    if uid is None:
        raise ValueError("authenticated user required")
    con.execute(
        "UPDATE upload_jobs SET progress=?, updated_at=? WHERE id=? AND owner_id=? AND status='cardgen'",
        (int(progress), now_iso(), job_id, uid),
    )
    con.commit()


def get_job(con, job_id, user_id=None):
    uid = _uid(user_id)
    if uid is None:
        raise ValueError("authenticated user required")
    row = con.execute("SELECT * FROM upload_jobs WHERE id=? AND owner_id=?", (job_id, uid)).fetchone()
    return dict(row) if row else None
