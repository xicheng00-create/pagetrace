"""幂等迁移旧状态；默认 dry-run，显式 --apply 才写库。"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path

from services.clock import now

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data-local" / "review.sqlite3"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not DB.exists():
        print("数据库不存在，跳过")
        return
    con = sqlite3.connect(DB)
    try:
        cards = con.execute("SELECT COUNT(*) FROM cards WHERE status='review'").fetchone()[0]
        reviews = con.execute(
            "SELECT COUNT(*) FROM card_reviews WHERE status='review'"
        ).fetchone()[0]
        if not args.apply:
            print(f"干跑：cards {cards}; card_reviews {reviews}")
            return
        backup_dir = ROOT / "data-local"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{DB.name}.bak.{now().strftime('%Y%m%d%H%M%S')}"
        shutil.copy2(DB, backup)
        con.execute("UPDATE cards SET status='reviewing' WHERE status='review'")
        con.execute(
            "UPDATE card_reviews SET status='reviewing' WHERE status='review'"
        )
        con.commit()
        print(f"备份 {backup}; cards {cards}; card_reviews {reviews}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
