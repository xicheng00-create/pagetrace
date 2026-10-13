"""上传校验与按整书指纹缓存抽文（UP-001/002）。"""

import hashlib
from pathlib import Path

import pymupdf
from flask import g, has_request_context

MAX_BYTES = 50 * 1024 * 1024
MAX_PAGES = 600


class DraftNotFound(ValueError):
    """Draft is missing, foreign, or not editable."""


class ExtractionError(Exception):
    """Document bytes could not be extracted into text."""


def validate_pdf(data, filename):
    if not filename.lower().endswith(".pdf") or not data.startswith(b"%PDF-"):
        raise ValueError("只支持 PDF 文件")
    if len(data) > MAX_BYTES:
        raise ValueError("文件超过 50 MB")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            pages = len(doc)
            if not 1 <= pages <= MAX_PAGES:
                raise ValueError("页数必须在 1 至 600 页之间")
            if doc.is_encrypted:
                raise ValueError("暂不支持加密 PDF")
            sample = min(5, pages)
            if sum(len(doc[i].get_text().strip()) for i in range(sample)) / sample < 100:
                raise ValueError("这本书没有文字层（可能是扫描件），暂不支持")
    except pymupdf.FileDataError as exc:
        raise ValueError("PDF 文件损坏，无法读取") from exc
    return {"book_hash": hashlib.sha256(data).hexdigest(), "pages": pages}


def extract_text(pdf_path, root):
    try:
        data = Path(pdf_path).read_bytes()
        book_hash = hashlib.sha256(data).hexdigest()
        target = Path(root) / "books" / book_hash / "raw.md"
        if target.exists():
            return {"book_hash": book_hash, "path": str(target), "cached": True}
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            text = "\n\n".join(f"<!-- p.{i + 1} -->\n\n{page.get_text()}" for i, page in enumerate(doc))
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(target)
        return {"book_hash": book_hash, "path": str(target), "cached": False}
    except (OSError, UnicodeError, pymupdf.FileDataError):
        raise ExtractionError("文档抽取失败") from None


def _uid(user_id=None):
    if user_id is not None:
        return user_id
    if not has_request_context():
        return 1
    return getattr(g, "user_id", None)


def find_pooled_book(con, book_hash, user_id=None):
    uid = _uid(user_id)
    if uid is None:
        raise ValueError("authenticated user required")
    row = con.execute("SELECT id FROM books WHERE book_hash=? AND owner_id=?", (book_hash, uid)).fetchone()
    return dict(row) if row else None


def accept_upload(con, data, filename, root, user_id=None):
    uid = _uid(user_id)
    if uid is None:
        raise ValueError("authenticated user required")
    metadata = validate_pdf(data, filename)
    from services.quota import check_quota

    check_quota(con, metadata["pages"], uid)
    pooled = find_pooled_book(con, metadata["book_hash"], uid)
    if pooled:
        return {**metadata, **pooled, "reused": True, "stage": "ready", "progress": 100}
    target = Path(root) / "in" / f"{metadata['book_hash']}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    created = not target.exists()
    try:
        if created:
            target.write_bytes(data)
        from services.clock import now_iso

        when = now_iso()
        cur = con.execute(
            "INSERT INTO upload_jobs(book_hash,filename,pages,status,stage,progress,created_at,updated_at,owner_id) "
            "VALUES(?,?,?,'queued','queued',0,?,?,?)",
            (metadata["book_hash"], filename, metadata["pages"], when, when, uid),
        )
        con.commit()
    except Exception:
        con.rollback()
        if created:
            target.unlink(missing_ok=True)
        raise
    return {"id": cur.lastrowid, **metadata, "stage": "queued", "progress": 0}


def save_drafts(con, job_id, rows, preserve=False, user_id=None):
    import json

    uid = _uid(user_id)
    if uid is None:
        raise ValueError("authenticated user required")
    from services.cardgen import final_rows
    from services.clock import now_iso

    rows = final_rows(rows)
    job = con.execute("SELECT book_hash FROM upload_jobs WHERE id=? AND owner_id=?", (job_id, uid)).fetchone()
    if job is None:
        raise ValueError("任务不存在")
    with con:
        existing = (
            {r[0] for r in con.execute("SELECT payload FROM card_drafts WHERE job_id=?", (job_id,))}
            if preserve
            else set()
        )
        if not preserve:
            con.execute("DELETE FROM card_drafts WHERE job_id=?", (job_id,))
        for row in rows:
            payload = json.dumps(row, ensure_ascii=False)
            if payload in existing:
                continue
            con.execute(
                "INSERT INTO card_drafts(job_id,book_hash,payload,confidence,created_at) VALUES(?,?,?,?,?)",
                (job_id, job["book_hash"], payload, row.get("confidence", "low"), now_iso()),
            )
    return len(rows)


def draft_state(con, user_id=None):
    import json

    uid = _uid(user_id)
    if uid is None:
        raise ValueError("authenticated user required")
    rows = con.execute(
        "SELECT d.* FROM card_drafts d JOIN upload_jobs j ON d.job_id=j.id "
        "WHERE j.owner_id=? AND j.status='ready' AND d.status IN ('kept','deleted') ORDER BY d.id",
        (uid,),
    ).fetchall()
    drafts = [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]
    can = any(r["status"] == "kept" for r in drafts)
    return {
        "drafts": drafts,
        "can_confirm": can,
        "reason": "" if can else "尚无保留的已完成草稿，暂不能确认入库",
    }


def set_draft(con, draft_id, status, user_id=None):
    uid = _uid(user_id)
    if uid is None:
        raise ValueError("authenticated user required")
    if status not in ("kept", "deleted"):
        raise ValueError("只允许保留或删除")
    cur = con.execute(
        "UPDATE card_drafts SET status=? WHERE id=? AND status IN ('kept','deleted') "
        "AND job_id IN (SELECT id FROM upload_jobs WHERE owner_id=? AND status='ready')",
        (status, draft_id, uid),
    )
    if cur.rowcount != 1:
        con.rollback()
        raise DraftNotFound("草稿不存在或不可操作")
    con.commit()


def confirm_drafts(con, user_id=None):
    import json

    uid = _uid(user_id)
    if uid is None:
        raise ValueError("authenticated user required")
    from ai.cardtext import to_card
    from scripts.ingest_store import content_hash, upsert_chapter, upsert_concept, upsert_subject

    from services.cardgen import validate
    from services.clock import now_iso

    rows = con.execute(
        "SELECT d.* FROM card_drafts d JOIN upload_jobs j ON d.job_id=j.id "
        "WHERE j.owner_id=? AND j.status='ready' AND d.status='kept' ORDER BY d.id",
        (uid,),
    ).fetchall()
    if not rows:
        raise ValueError("尚无可确认草稿")
    validated = [(r, validate(json.loads(r["payload"]))) for r in rows]
    with con:
        for draft, row in validated:
            if sum(map(len, row["answer_points"])) > 222:
                raise ValueError("长度闸门拒绝确认")
            when = now_iso()
            sid = upsert_subject(con, row["subject"], when)
            existing = find_pooled_book(con, draft["book_hash"], uid)
            if existing:
                bid = existing["id"]
            else:
                bid = con.execute(
                    "INSERT INTO books(subject_id,title,slug,source,book_hash,created_at,owner_id) VALUES(?,?,?,'upload',?,?,?)",
                    (
                        sid,
                        row["book"] + "（上传）",
                        "upload-" + draft["book_hash"],
                        draft["book_hash"],
                        when,
                        uid,
                    ),
                ).lastrowid
            chid = upsert_chapter(con, bid, row["chapter"], row.get("chapter_title"))
            concept_uid = draft["book_hash"] + ":" + row["concept_id"]
            cid = upsert_concept(
                con, chid, concept_uid, row.get("pages"), row.get("confidence"), row.get("tags")
            )
            front, back = to_card(row["question"], row["answer_points"])
            con.execute(
                "INSERT OR IGNORE INTO cards(concept_id,subject_id,title,front,back,source,content_hash,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    cid,
                    sid,
                    row["title"],
                    front,
                    back,
                    row["book"] + "/" + row["chapter"],
                    content_hash(front, back),
                    when,
                ),
            )
            con.execute(
                "UPDATE card_drafts SET status='confirmed' WHERE id=? AND job_id IN (SELECT id FROM upload_jobs WHERE owner_id=?)",
                (draft["id"], uid),
            )
    return {"confirmed": len(rows)}
