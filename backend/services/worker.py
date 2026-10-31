"""UP-008：进程内单线程排队；中间态重启从缓存重放，不引入外部服务。"""

import logging
import os
import threading
from pathlib import Path

from data.db import get_db

from services import cardgen, llm
from services.jobs import get_job, set_progress, transition
from services.segment import SegmentationError, segment_book
from services.upload import ExtractionError, extract_text, save_drafts

logger = logging.getLogger(__name__)
LOCK = threading.Lock()
THREADS = {}
STATE_LOCK = threading.Lock()
PENDING = set()


def _failure_kind(exc):
    if isinstance(exc, (ExtractionError, SegmentationError, OSError, UnicodeError)):
        return "parse"
    if isinstance(exc, llm.LLMError):
        return "provider"
    if isinstance(exc, cardgen.CardParseError):
        return "parse"
    if isinstance(exc, cardgen.CardGateError):
        return "gate"
    # Unknown exceptions default to provider: never misdirect users to change cards.
    return "provider"


def _failure_message(kind):
    return {"provider": "模型服务错误", "parse": "文档解析错误", "gate": "卡片校验未通过"}[kind]


def run_job(con, job_id, root, user_id):
    job = get_job(con, job_id, user_id)
    if job is None or job["status"] in ("ready", "failed"):
        return
    stages = ["queued", "extracting", "segmenting", "cardgen", "gated", "ready"]

    def advance(stage, progress):
        current = get_job(con, job_id, user_id)["status"]
        if stages.index(current) < stages.index(stage):
            transition(con, job_id, stage, progress, user_id=user_id)

    try:
        advance("extracting", 10)
        pdf = Path(root) / "in" / (job["book_hash"] + ".pdf")
        raw = extract_text(pdf, root)
        advance("segmenting", 20)
        blocks = segment_book(raw["path"], job["book_hash"])["blocks"]
        advance("cardgen", 30)
        retries = min(3, max(0, int(os.environ.get("UPLOAD_BLOCK_RETRIES", "2"))))
        failed = []
        total_blocks = len(blocks)
        for idx, block in enumerate(blocks):
            for attempt in range(retries + 1):
                try:
                    save_drafts(
                        con, job_id, cardgen.generate_block(block, root), preserve=True, user_id=user_id
                    )
                    break
                except Exception as exc:
                    kind = _failure_kind(exc)
                    logger.error("upload job=%s exception=%s category=%s", job_id, type(exc).__name__, kind)
                    if attempt == retries:
                        failed.append(kind)
            # 块级进度：30% → 90%，让用户看到真实推进（失败块也计入，避免停在 30%）
            try:
                set_progress(con, job_id, 30 + (60 * (idx + 1)) // max(total_blocks, 1), user_id=user_id)
            except Exception as exc:  # 进度写失败不得中断出卡
                logger.error("upload job=%s progress exception=%s", job_id, type(exc).__name__)
        if not blocks or len(failed) == len(blocks):
            kind = failed[0] if failed else "parse"
            transition(con, job_id, "failed", 0, f"{kind}: {_failure_message(kind)}", user_id=user_id)
            return
        summary = (
            (
                f"{len(blocks)} 块中 {len(failed)} 块未过；"
                + "、".join(f"{kind}：{_failure_message(kind)}" for kind in sorted(set(failed)))
            )
            if failed
            else None
        )
        advance("gated", 90)
        advance("ready", 100)
        if summary:
            con.execute(
                "UPDATE upload_jobs SET error=? WHERE id=? AND owner_id=?", (summary, job_id, user_id)
            )
            con.commit()
    except Exception as exc:
        con.rollback()
        kind = _failure_kind(exc)
        logger.error("upload job=%s exception=%s category=%s", job_id, type(exc).__name__, kind)
        transition(con, job_id, "failed", 0, f"{kind}: {_failure_message(kind)}", user_id=user_id)


def drain(app):
    # 所有 app/请求共用锁；同进程绝不并跑两个任务。
    with LOCK, app.app_context():
        con = get_db()
        root = app.config.get("UPLOAD_ROOT", str(Path(app.root_path).parent / "data-local/uploads"))
        while True:
            # 后台调度没有请求身份：逐用户取候选，再维持原有全局 id FIFO。
            candidates = []
            for user in con.execute("SELECT id FROM users ORDER BY id").fetchall():
                owner_id = user["id"]
                candidate = con.execute(
                    "SELECT id,owner_id FROM upload_jobs WHERE owner_id=? "
                    "AND status NOT IN ('ready','failed') ORDER BY id LIMIT 1", (owner_id,)
                ).fetchone()
                if candidate is not None:
                    candidates.append(candidate)
            job = min(candidates, key=lambda row: row["id"], default=None)
            if job is None:
                return
            logger.info("upload job %s start", job["id"])
            run_job(con, job["id"], root, job["owner_id"])
            logger.info(
                "upload job %s end status=%s", job["id"], get_job(con, job["id"], job["owner_id"])["status"]
            )


def _consume(app):
    key = id(app)
    try:
        while True:
            try:
                drain(app)
            except BaseException as exc:
                logger.error("upload worker exception type=%s", type(exc).__name__)
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    return
            with STATE_LOCK:
                if key in PENDING:
                    PENDING.discard(key)
                    continue
                return
    finally:
        with STATE_LOCK:
            THREADS.pop(key, None)
            PENDING.discard(key)


def start(app):
    if not app.config.get("UPLOAD_WORKER_ENABLED", False):
        return
    key = id(app)
    with STATE_LOCK:
        if key in THREADS:
            PENDING.add(key)
            return
        try:
            thread = threading.Thread(target=_consume, args=(app,), daemon=True, name="upload-worker")
            THREADS[key] = thread
            thread.start()
        except Exception:
            THREADS.pop(key, None)
            PENDING.discard(key)
            logger.error("upload worker could not start; retry on next enqueue")
