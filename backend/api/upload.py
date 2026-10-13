"""PDF 上传唯一入口；验证通过前不建任务、不落盘。"""

from pathlib import Path

from data.db import get_db
from flask import Blueprint, current_app, g, request
from middleware.errors import e_input, e_not_found, err, ok
from services.quota import QuotaError, quota_state
from services.upload import MAX_BYTES, accept_upload

bp = Blueprint("upload", __name__)


@bp.post("/api/upload")
def upload():
    file = request.files.get("file")
    if file is None or not file.filename or len(file.filename) > 255:
        return e_input("请选择 PDF 文件（文件名不超过 255 字）")
    root = current_app.config.get("UPLOAD_ROOT", str(Path(current_app.root_path).parent / "data-local/uploads"))
    try:
        result = accept_upload(get_db(), file.read(MAX_BYTES + 1), file.filename, root, g.user_id)
        from services.worker import start

        start(current_app._get_current_object())
        return ok(result, 202)
    except QuotaError as exc:
        return err("E_QUOTA", str(exc), 429)
    except ValueError as exc:
        return e_input(str(exc))


@bp.get("/api/upload/jobs/<int:job_id>")
def job(job_id):
    from middleware.errors import e_not_found
    from services.jobs import get_job

    result = get_job(get_db(), job_id, g.user_id)
    return ok(result) if result else e_not_found()


@bp.get("/api/upload/quota")
def quota():
    return ok(quota_state(get_db(), g.user_id))


@bp.get("/api/drafts")
def drafts():
    from services.upload import draft_state

    return ok(draft_state(get_db(), g.user_id))


@bp.put("/api/drafts/<int:draft_id>")
def change_draft(draft_id):
    from services.upload import DraftNotFound, set_draft

    try:
        set_draft(get_db(), draft_id, (request.get_json(silent=True) or {}).get("status"), g.user_id)
        return ok({"updated": True})
    except DraftNotFound as exc:
        return e_not_found(str(exc))
    except ValueError as exc:
        return e_input(str(exc))


@bp.post("/api/drafts/confirm")
def confirm():
    from services.upload import confirm_drafts

    try:
        return ok(confirm_drafts(get_db(), g.user_id))
    except ValueError as exc:
        return e_input(str(exc))
