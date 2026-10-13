"""UP-010 运维入口：默认只读；pm --apply 时先备份，再迁移并对账。"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.models import migrate_upload  # noqa: E402
from services.clock import now_iso  # noqa: E402


def evidence(con):
    result = {}
    for table, stamp in [('card_reviews', 'learned_at'), ('quiz_attempts', 'created_at')]:
        count, latest = con.execute(f'SELECT COUNT(*), MAX({stamp}) FROM {table}').fetchone()
        rows = con.execute(f'SELECT * FROM {table} ORDER BY id LIMIT 20').fetchall()
        result[table] = {'count': count, 'latest': latest,
                         'sample_sha256': hashlib.sha256(repr(rows).encode()).hexdigest()}
    return result


def run(path, apply=False):
    path = Path(path).resolve()
    print(f'目标库: {path}')
    print("将执行 DDL: ALTER TABLE books ADD COLUMN book_hash TEXT (如缺失); ALTER TABLE books ADD COLUMN source TEXT (如缺失); CREATE UNIQUE INDEX uq_books_hash; CREATE TABLE upload_jobs; CREATE TABLE card_drafts")
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as source:
        before = evidence(source)
        existing = {r[0] for r in source.execute("SELECT name FROM sqlite_master")}
        changed = not {'uq_books_hash', 'upload_jobs', 'card_drafts'} <= existing
        if not changed:
            print('0 变化')
        if not apply:
            return {'dry_run': True, 'before': before}
        backup = path.with_name(path.name + '.' + now_iso().replace(':', '-') + '.bak')
        with sqlite3.connect(backup) as target:
            source.backup(target)
    with sqlite3.connect(path) as con:
        migrate_upload(con)
        after = evidence(con)
        if after != before:
            raise RuntimeError('历史记录对账不一致，迁移已回滚')
    return {'backup': str(backup), 'before': before, 'after': after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.database, args.apply), ensure_ascii=False))


if __name__ == '__main__':
    main()
