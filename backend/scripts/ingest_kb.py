"""上游 ingest（CARD-001）：只读 `exports/<学科>/<书>.jsonl`（契约 §5）→ 落库。

用法：
    ingest_kb.py                      # 扫 KB_EXPORTS_DIR 下所有 jsonl
    ingest_kb.py --subject psychology # 只跑某学科目录
    ingest_kb.py --book 合成示例书1-第6版 # 单本书（需配 --subject 定位；仅给书名则全盘搜）
    ingest_kb.py --file path.jsonl    # 单文件（测试/定向重放）
    ingest_kb.py --dry-run            # 只校验与去重，不写库

铁律：
- 必填字段缺失 → 该行拒绝入库并计入 rejected（不补默认值、不猜）。
- contract != CONTRACT_VERSION → **整文件拒绝**，一行不写。
- 幂等：同 (concept_id, content_hash) 第二次跑 → 跳过。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai import cardgate  # noqa: E402
from ai.cardtext import to_card  # noqa: E402
from config import BaseConfig  # noqa: E402
from services import unlock  # noqa: E402

# 复用库/校验/upsert（re-export 以兼容既有测试与外部调用）
from scripts.ingest_store import (  # noqa: E402,F401
    REQUIRED,
    connect,
    content_hash,
    resolve_db_path,
    upsert_book,
    upsert_chapter,
    upsert_concept,
    upsert_subject,
    validate_contract,
)
from scripts.ingest_store import pages_text as _pages_text  # noqa: E402


def _source_text(o: dict, chapter_name: str) -> str:
    """卡片可回溯来源：有页码 →「书/章/页」；无页码（EPUB 源）→ 退化为「书/章」。"""
    p = _pages_text(o.get("pages"))
    return f"{o['book']}/{chapter_name}" + (f"/{p}" if p else "")

TZ8 = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(TZ8).isoformat(timespec="seconds")


# —— 单文件 ingest ——

def _collect_files(exports_dir: Path, subject: str | None, book: str | None,
                   file: str | None) -> list[Path]:
    if file:
        return [Path(file)]
    if book and subject:
        return [exports_dir / subject / f"{book}.jsonl"]
    hits = sorted(exports_dir.glob(f"*/{book}.jsonl" if book else "*/*.jsonl"))
    if subject:
        hits = [p for p in hits if p.parent.name == subject]
    return hits


def ingest_file(con, path: Path, *, dry_run: bool = False) -> dict:
    stats = {"file": str(path), "new": 0, "backfilled": 0, "merged": 0, "dropped": 0,
             "skipped": 0,
             "rejected": 0, "reasons": [], "unlocked": [], "book_id": None,
             "subject_id": None, "contract_ok": True}
    when = _now()

    raw_lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    objs: list[dict] = []
    for i, ln in enumerate(raw_lines, 1):
        try:
            objs.append(json.loads(ln))
        except json.JSONDecodeError:
            stats["rejected"] += 1
            stats["reasons"].append(f"L{i} 非法 JSON")

    # 整文件契约版本：任一行 contract 不符 → 整文件拒绝
    bad_contract = [i for i, o in enumerate(objs, 1)
                    if not isinstance(o, dict) or o.get("contract") != BaseConfig.CONTRACT_VERSION]
    if bad_contract:
        stats["contract_ok"] = False
        stats["rejected"] += len(raw_lines)
        stats["reasons"].append(
            f"contract≠{BaseConfig.CONTRACT_VERSION}，整文件拒绝（行 {bad_contract}）")
        return stats

    # 逐行契约校验 + 成卡
    cards: list[dict] = []
    for i, o in enumerate(objs, 1):
        reason = validate_contract(o, BaseConfig.CONTRACT_VERSION)
        if reason:
            stats["rejected"] += 1
            stats["reasons"].append(f"L{i} {reason}")
            continue
        front, back = to_card(o["question"], o["answer_points"])
        if not front or not back:
            stats["rejected"] += 1
            stats["reasons"].append(f"L{i} 卡面为空")
            continue
        cards.append({"_obj": o, "_line": i, "concept_uid": o["concept_id"],
                      "front": front, "back": back,
                      "title": str(o.get("title") or "").strip() or None,
                      "answer_points": list(o["answer_points"])})

    kept, merged_pairs, dropped = cardgate.dedup_cards(cards)
    stats["merged"] = len(merged_pairs)
    stats["dropped"] = len(dropped)

    if not kept:
        return stats

    if dry_run:
        for c in kept:
            exists = con.execute(
                "SELECT 1 FROM cards c JOIN concepts cp ON cp.id=c.concept_id"
                " WHERE cp.concept_uid=? AND c.content_hash=?",
                (c["concept_uid"], content_hash(c["front"], c["back"]))).fetchone()
            stats["skipped" if exists else "new"] += 1
        return stats

    objs_by_line = {c["_line"]: c["_obj"] for c in cards}
    first_chapter: dict[int, int] = {}
    for c in kept:
        o = objs_by_line[c["_line"]]
        sid = upsert_subject(con, o["subject"], when)
        bid, is_new_book = upsert_book(con, sid, o["book"], str(path), when)
        chid = upsert_chapter(con, bid, o["chapter"], o.get("chapter_title"))
        chapter_name = con.execute("SELECT name FROM chapters WHERE id=?", (chid,)).fetchone()["name"]
        source = _source_text(o, chapter_name)
        cid = upsert_concept(con, chid, o["concept_id"], o.get("pages"),
                             o.get("confidence"), o.get("tags"))
        stats["subject_id"], stats["book_id"] = sid, bid
        first_chapter.setdefault(bid, chid)

        exists = con.execute(
            "SELECT id, title, source FROM cards WHERE concept_id=? AND content_hash=?",
            (cid, content_hash(c["front"], c["back"]))).fetchone()
        if exists:
            stats["skipped"] += 1
            if exists["source"] != source:
                con.execute("UPDATE cards SET source=? WHERE id=?", (source, exists["id"]))
            # CARD-007 回填：既有行补/顺 title（幂等 —— 已有同值则不写，第二次跑回填 0）。
            if (exists["title"] or "") != (c["title"] or ""):
                con.execute("UPDATE cards SET title=? WHERE id=?", (c["title"], exists["id"]))
                stats["backfilled"] += 1
            continue
        con.execute(
            "INSERT INTO cards(concept_id, subject_id, front, back, source, title,"
            " content_hash, status, created_at) VALUES(?,?,?,?,?,?,?, 'new', ?)",
            (cid, sid, c["front"], c["back"], source, c["title"],
             content_hash(c["front"], c["back"]), when))
        stats["new"] += 1
        if is_new_book:
            first_chapter[bid] = chid

    # 新书入库即解锁第 1 章（SCHED-001）+ 连锁评估
    stats["unlocked"] = unlock.maybe_unlock(con)
    con.commit()
    return stats


def scan_kb(con, exports_dir: Path, *, subject=None, book=None, file=None,
            dry_run=False) -> list[dict]:
    paths = _collect_files(exports_dir, subject, book, file)
    return [ingest_file(con, p, dry_run=dry_run) for p in paths if p.exists()]


def write_audit(results: list[dict], when: str) -> Path:
    audit_dir = REPO_ROOT / "reports"
    audit_dir.mkdir(exist_ok=True)
    path = audit_dir / f"ingest-{when[:10]}.md"
    lines = [f"# ingest 审计 {when}", "",
             "| 文件 | 新增 | 回填 | 合并 | 丢弃 | 跳过 | 待人工 | contract |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append("| {file} | {new} | {backfilled} | {merged} | {dropped} | {skipped} | {rejected} | {ok} |".format(
            ok="✓" if r["contract_ok"] else "✗ 整文件拒绝", **r))
    reasons = [(r["file"], x) for r in results for x in r["reasons"]]
    if reasons:
        lines += ["", "## 待人工 / 拒绝明细", ""]
        lines += [f"- `{f}` · {x}" for f, x in reasons]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="KB 导出契约 → 复习库")
    ap.add_argument("--file")
    ap.add_argument("--subject")
    ap.add_argument("--book")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)

    exports = Path(BaseConfig.KB_EXPORTS_DIR)
    con = connect(args.db or resolve_db_path())
    started = _now()
    try:
        results = scan_kb(con, exports, subject=args.subject, book=args.book,
                          file=args.file, dry_run=args.dry_run)
        for r in results:
            tot_new = r["new"]
            print(f"[{r['file']}] 新增 {tot_new} / 回填 {r['backfilled']} / 合并 {r['merged']}"
                  f" / 跳过 {r['skipped']} / 待人工 {r['rejected']}"
                  + ("（dry-run）" if args.dry_run else ""))
            for x in r["reasons"]:
                print(f"    ⚠ {x}")
        if results and not args.dry_run:
            for r in results:
                con.execute(
                    "INSERT INTO ingest_runs(subject_id, book_id, new_count, merged_count,"
                    " skipped_count, rejected_count, contract_version, started_at, finished_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (r["subject_id"], r["book_id"], r["new"], r["merged"], r["skipped"],
                     r["rejected"], BaseConfig.CONTRACT_VERSION, started, _now()))
            con.commit()
            ap_path = write_audit(results, started)
            print(f"审计：{ap_path}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
