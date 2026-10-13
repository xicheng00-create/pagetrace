"""Safely reswap an existing book's cards（就地换文，保住卡 id 与复习进度）。

两种配对方式（CARD-008）：
- `--match order`（默认，QUIZ-010 的英文卡面换文路径）：同 concept 内按 id 顺序配，要求两侧卡数相同；
- `--match back`（换版入库）：同 concept 内按 `back` 逐字唯一配对，允许两侧卡数不同；
  配不上 / 命中多张 → 整批拒绝、库零改动（不猜、不近似配）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from ai.cardtext import to_card  # noqa: E402

from scripts.ingest_store import _owner_id, content_hash  # noqa: E402

DEFAULT_SOURCE = Path.home() / "data-local/exports/management/合成示例书1.jsonl"


def row_card(row: dict) -> tuple[str, str]:
    """source 行 → (front, back)，与 ingest 同源（`ai.cardtext.to_card`，含要点去重）。"""
    answer = row.get("answer_points") or row.get("back") or []
    return to_card(
        row.get("question", row.get("front", "")), answer if isinstance(answer, list) else [answer]
    )


def pair_by_back(dbby: dict, incoming: list[dict]) -> tuple[list, int, int, list[str]]:
    """按「同 concept 内背面逐字相同」1:1 配对。

    返回 (配对, 库内未配对卡数, 上游新增行数, 问题清单)。
    - 库内没有同正文的卡 → 该行是**上游新增/正文真变**，不是本工具的活：跳过并计数（交 ingest 新增 + 退场收尾）；
    - 同 concept 内背面命中 >1 张 → 记问题，调用方**整批拒绝**（不猜、不近似配）。
    """
    available = defaultdict(list)
    for concept_id, db_rows in dbby.items():
        for r in db_rows:
            available[(concept_id, r["back"])].append(r)
    pairs, problems, new_rows, claimed = [], [], 0, set()
    for row in incoming:
        _front, back = row_card(row)
        cands = [c for c in available.get((row.get("concept_id"), back), []) if c["id"] not in claimed]
        if not cands:
            new_rows += 1
            continue
        if len(cands) > 1:
            problems.append(f"concept {row.get('concept_id')}: 背面唯一配对失败（命中 {len(cands)} 张）")
            continue
        claimed.add(cands[0]["id"])
        pairs.append((cands[0], row))
    return pairs, sum(len(v) for v in dbby.values()) - len(claimed), new_rows, problems


def rows(path: Path) -> list[dict]:  # pragma: no cover
    return [json.loads(line) for line in path.read_text(encoding="utf8").splitlines() if line.strip()]


def main(argv=None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--book", required=True)
    parser.add_argument(
        "--match",
        choices=("order", "back"),
        default="order",
        help="order=同 concept 内按 id 顺序（须两侧卡数相同，原行为）；"
        "back=同 concept 内按背面逐字相同（允许卡数不同，配不上即整批拒绝）",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    incoming = rows(args.source)
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    book = con.execute(
        "SELECT id FROM books WHERE (title=? OR slug=?) AND owner_id=?",
        (args.book, args.book, _owner_id(con)),
    ).fetchone()
    if not book:
        print(f"rejected: book not found: {args.book}", file=sys.stderr)
        return 2

    chapters = [r["id"] for r in con.execute("SELECT id FROM chapters WHERE book_id=?", (book["id"],))]
    if not chapters:
        print("rejected: book has no chapters", file=sys.stderr)
        return 2
    marks = ",".join("?" for _ in chapters)
    concepts = dict(
        con.execute(f"SELECT id, concept_uid FROM concepts WHERE chapter_id IN ({marks})", chapters)
    )
    if not concepts:
        print("rejected: book has no concepts", file=sys.stderr)
        return 2
    marks = ",".join("?" for _ in concepts)
    dbrows = con.execute(
        f"SELECT c.id, cp.concept_uid, ch.name AS chapter, c.front, c.back, c.source, c.content_hash "
        f"FROM cards c JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id WHERE cp.id IN ({marks}) "
        "ORDER BY cp.concept_uid, c.id",
        list(concepts),
    ).fetchall()
    dbby = defaultdict(list)
    for row in dbrows:
        dbby[row["concept_uid"]].append(row)

    orphans = 0
    new_rows = 0
    if args.match == "order":
        counts = Counter(row.get("concept_id") for row in incoming)
        diffs = []
        for concept_id, count in counts.items():
            if count != len(dbby.get(concept_id, [])):
                diffs.append(f"concept {concept_id}: source={count}, db={len(dbby.get(concept_id, []))}")
        if sum(counts.values()) != len(dbrows):
            diffs.append(f"total: source={sum(counts.values())}, db={len(dbrows)}")
        if diffs:
            print("rejected: row counts differ\n" + "\n".join(diffs), file=sys.stderr)
            return 2
        pairs = [(dbby[row["concept_id"]].pop(0), row) for row in incoming]
    else:
        pairs, orphans, new_rows, problems = pair_by_back(dbby, incoming)
        if problems:
            print("rejected: 背面唯一配对失败\n" + "\n".join(problems), file=sys.stderr)
            return 2

    changes = []
    unchanged = 0
    chapter_counts = defaultdict(lambda: {"changed": 0, "unchanged": 0})
    for old, row in pairs:
        front, back = row_card(row)
        source = row.get("source", old["source"])
        new_hash = content_hash(front, back)
        if (front, back, source, new_hash) == (old["front"], old["back"], old["source"], old["content_hash"]):
            unchanged += 1
            chapter_counts[old["chapter"]]["unchanged"] += 1
        else:
            changes.append((old, source, front, back, new_hash))
            chapter_counts[old["chapter"]]["changed"] += 1

    print(f"changed={len(changes)} unchanged={unchanged} rejected=0")
    for chapter, counts in sorted(chapter_counts.items()):
        print(f"chapter={chapter} changed={counts['changed']} unchanged={counts['unchanged']}")
    print(f"new_content_hashes={len({item[4] for item in changes})}")
    if args.match == "back":
        print(
            f"unmatched_db={orphans}（上游已不产出、留待退场）· "
            f"new_rows={new_rows}（库内无同正文 → 由 ingest 新增）"
        )
    for old, _source, front, back, _hash in changes[:5]:
        print(
            f"{old['id']}: front {old['front'][:60]!r} => {front[:60]!r}; back {old['back'][:60]!r} => {back[:60]!r}"
        )
    if not args.apply:
        return 0

    con.execute("PRAGMA wal_checkpoint(FULL)")
    backup = (
        args.db.parent
        / "backups"
        / f"review-{datetime.fromtimestamp(time.time()):%Y%m%d-%H%M%S}-pre-{args.match}-reswap.sqlite3"
    )
    backup.parent.mkdir(exist_ok=True)
    shutil.copy2(args.db, backup)
    try:
        for old, source, front, back, new_hash in changes:
            con.execute(
                "UPDATE cards SET front=?, back=?, source=?, content_hash=? WHERE id=?",
                (front, back, source, new_hash, old["id"]),
            )
        con.commit()
    except sqlite3.IntegrityError:
        con.rollback()
        print("rejected: content_hash conflict", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
