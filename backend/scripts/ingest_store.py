"""ingest 的库连接 / 契约校验 / upsert（从 ingest_kb 拆出，保持单文件 <300 行）。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from pathlib import Path

from config import BaseConfig
from data import models

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

# pages 为**可选**（2026-09-26）：知识库源是 EPUB，无真实页码（raw 章文件只到章粒度），
# 缺失/空数组时 source 退化为「书/章」，不再拒收整行。
REQUIRED = ("contract", "concept_id", "subject", "book", "chapter", "title", "question", "answer_points")


def resolve_db_path() -> str:
    path = getattr(os, "environ").get("DATABASE_PATH")
    if path:
        return path
    uri = getattr(BaseConfig, "SQLALCHEMY_DATABASE_URI", "sqlite:///data-local/review.sqlite3")
    if uri.startswith("sqlite:///"):
        p = uri[len("sqlite:///") :]
        return p if os.path.isabs(p) else str(REPO_ROOT / p)
    return str(REPO_ROOT / "data-local" / "review.sqlite3")


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(models.SCHEMA)
    models.migrate(con)
    models.migrate_upload(con)
    # 测试/入库临时库也必须具备与应用相同的 S2 结构；生产库迁移仍由 PM 显式执行。
    import importlib.util
    migration_path = REPO_ROOT / "scripts" / "migrate_s2_multiuser.py"
    spec = importlib.util.spec_from_file_location("s2_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    con.commit()
    con.close()
    migration.migrate(path)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


# —— 契约校验（§5）——


def validate_contract(obj: dict, expected: int) -> str | None:
    """返回拒绝原因；None = 通过。整文件级校验（contract 必须先过）。"""
    if not isinstance(obj, dict):
        return "非 JSON 对象"
    if obj.get("contract") != expected:
        return f"contract={obj.get('contract')!r} ≠ {expected}"
    for f in REQUIRED:
        if f not in obj or obj[f] in (None, "", []):
            return f"缺必填字段 {f}"
    if not isinstance(obj.get("answer_points"), list) or not obj["answer_points"]:
        return "answer_points 必须为非空数组"
    title = obj.get("chapter_title")
    if "chapter_title" in obj and (
        not isinstance(title, str) or len(title) > 40 or "\n" in title or "\r" in title
    ):
        return "chapter_title 必须为不超过 40 字且不含换行的字符串"
    pages = obj.get("pages")
    if pages not in (None, "", []):  # 可选：给了就必须合法
        if not (isinstance(pages, list) or (isinstance(pages, str) and pages.strip())):
            return "pages 必须为数组或区间字符串"
    return None


def content_hash(front: str, back: str) -> str:
    return hashlib.sha256(f"{front}\x00{back}".encode()).hexdigest()


def pages_text(pages) -> str:
    """页码文本；None/空 → \"\"（EPUB 无真实页码，source 退到「书/章」）。"""
    if pages in (None, "", []):
        return ""
    if isinstance(pages, list):
        return ",".join(str(p) for p in pages)
    return str(pages)


# —— 库内 upsert ——


def subject_label(slug: str) -> str | None:
    """slug → 显示名；未映射返回 None（DATA-006）。"""
    return getattr(BaseConfig, "SUBJECT_LABELS", {}).get(slug)


def upsert_subject(con, slug: str, when: str) -> int:
    """学科 upsert（DATA-006）：**已存在就完全不写 name** —— 重导入不得冲掉已改好的显示名。

    只新建时按 SUBJECT_LABELS 取显示名；未命中回落 slug 并记一条 warning。
    """
    row = con.execute("SELECT id FROM subjects WHERE slug=?", (slug,)).fetchone()
    if row:
        return row["id"]  # 幂等：既有学科的 name 一律不碰（含已回填/已手工修好的值）
    label = subject_label(slug)
    if label is None:
        logger.warning("学科 %s 无显示名映射，暂用 slug（在 config.SUBJECT_LABELS 补一行即可）", slug)
        label = slug
    cur = con.execute(
        "INSERT INTO subjects(name, slug, order_no, created_at) VALUES(?,?,?,?)", (label, slug, 0, when)
    )
    return cur.lastrowid


def backfill_subject_labels(con, labels: dict[str, str] | None = None) -> list[dict]:
    """按映射一次性回填既有学科的显示名（幂等；**映射里没有的行一动不动**）。

    返回逐行 before/after 账（含未变动的行，供 run 后打印核对）。
    """
    labels = BaseConfig.SUBJECT_LABELS if labels is None else labels
    out = []
    for r in con.execute("SELECT id, slug, name FROM subjects ORDER BY id").fetchall():
        want = labels.get(r["slug"])
        changed = want is not None and want != r["name"]
        if changed:
            con.execute("UPDATE subjects SET name=? WHERE id=?", (want, r["id"]))
        out.append(
            {
                "id": r["id"],
                "slug": r["slug"],
                "before": r["name"],
                "after": want if changed else r["name"],
                "changed": changed,
            }
        )
    return out


def _owner_id(con):
    row = con.execute("SELECT id FROM users WHERE username=?", (BaseConfig.S2_OWNER_USERNAME,)).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,'!BOOTSTRAP_PASSWORD_REQUIRED!','owner',datetime('now'))", (BaseConfig.S2_OWNER_USERNAME,)
        )
        row = con.execute("SELECT id FROM users WHERE username=?", (BaseConfig.S2_OWNER_USERNAME,)).fetchone()
    return row["id"]


def upsert_book(con, subject_id: int, slug: str, path: str, when: str) -> tuple[int, bool]:
    row = con.execute(
        "SELECT id FROM books WHERE subject_id=? AND slug=? AND owner_id=?",
        (subject_id, slug, _owner_id(con)),
    ).fetchone()
    if row:
        return row["id"], False
    cur = con.execute(
        "INSERT INTO books(subject_id, title, slug, source_path, status, created_at, owner_id)"
        " VALUES(?,?,?,?,'active',?,?)",
        (subject_id, slug, slug, path, when, _owner_id(con)),
    )
    return cur.lastrowid, True


def chapter_order(anchor: str) -> int:
    """章序：从 `第N章` 抽 N（没有数字 → 0，保持插入序）。

    修 2026-09-26 的缺陷：order_no 原先取「插入序」，导出文件按概念排列，
    导致第12章排在第1章前面，前端钻取列表顺序错乱。
    """
    m = re.search(r"(\d+)", str(anchor))
    return int(m.group(1)) if m else 0


def upsert_chapter(con, book_id: int, anchor: str, title: str | None = None) -> int:
    """章锚点为稳定键；缺标题时保留已人工补全的章名。"""
    order = chapter_order(anchor)
    name = f"{anchor} · {title}" if title else anchor
    row = con.execute(
        "SELECT id, name, order_no FROM chapters WHERE book_id=? AND anchor=?", (book_id, anchor)
    ).fetchone()
    if row:
        # 旧契约缺标题时不冲掉已经人工修好的章显示名。
        if title and row["name"] != name:
            con.execute("UPDATE chapters SET name=? WHERE id=?", (name, row["id"]))
        if row["order_no"] != order:  # 幂等修正既有行的章序
            con.execute("UPDATE chapters SET order_no=? WHERE id=?", (order, row["id"]))
        return row["id"]
    cur = con.execute(
        "INSERT INTO chapters(book_id, name, order_no, anchor, status) VALUES(?,?,?,?, 'locked')",
        (book_id, name, order, anchor),
    )
    return cur.lastrowid


def upsert_concept(con, chapter_id: int, uid: str, pages, confidence, tags) -> int:
    row = con.execute("SELECT id FROM concepts WHERE concept_uid=?", (uid,)).fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO concepts(concept_uid, chapter_id, name, source_pages, confidence, tags)"
        " VALUES(?,?,?,?,?,?)",
        (
            uid,
            chapter_id,
            uid,
            pages_text(pages),
            confidence,
            json.dumps(tags, ensure_ascii=False) if tags else None,
        ),
    )
    return cur.lastrowid
