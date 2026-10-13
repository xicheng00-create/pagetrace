"""一次性回填学科显示名（DATA-006）：把库里既有 subjects 按 config.SUBJECT_LABELS 更新 name。

用法：
    backend/scripts/backfill_subject_labels.py [--db 路径] [--dry-run]

纪律：
- **先备份**（带时间戳副本，wal_checkpoint 先行；旧份不删），再改数据。
- 幂等：映射里没有的 slug 一动不动；重复跑第二次「变更 0 行」。
- 打印 before/after 账，便于人工核对。
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.ingest_store import backfill_subject_labels, connect, resolve_db_path  # noqa: E402

TZ8 = timezone(timedelta(hours=8))


def backup_db(db_path: str) -> Path:
    """wal_checkpoint 先行，再落一份带时间戳的副本到 backups/（已存在同名则不加后缀）。"""
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()
    finally:
        con.close()
    stamp = datetime.now(TZ8).strftime("%Y%m%d-%H%M%S")
    dest = REPO_ROOT / "backups" / f"review-{stamp}-pre-subject-labels.sqlite3"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db_path, dest)
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按 SUBJECT_LABELS 回填学科显示名（幂等）")
    ap.add_argument("--db", default=None, help="库路径（默认按配置解析）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将发生的变更，不写库、不备份")
    args = ap.parse_args(argv)

    db_path = args.db or resolve_db_path()
    if not Path(db_path).exists():
        print(f"无库文件：{db_path}")
        return 1

    if args.dry_run:
        con = connect(db_path)
        rows = backfill_subject_labels(con)
        con.rollback()
    else:
        bk = backup_db(db_path)
        print(f"备份：{bk}")
        con = connect(db_path)
        rows = backfill_subject_labels(con)
        con.commit()
    con.close()

    changed = sum(1 for r in rows if r["changed"])
    for r in rows:
        mark = "→ 改" if r["changed"] else "  不动"
        print(f"{mark}  #{r['id']} {r['slug']}: {r['before']!r} → {r['after']!r}")
    print(f"合计 {len(rows)} 个学科，变更 {changed} 行"
          + ("（dry-run，未写库）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
