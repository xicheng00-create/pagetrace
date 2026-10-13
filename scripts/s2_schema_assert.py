#!/usr/bin/env python3
"""Read-only assertions for S2 ownership, derived tables and tenant indexes."""
import sqlite3
import sys
from pathlib import Path

OWNED = {'books': 'owner_id', 'upload_jobs': 'owner_id', 'card_reviews': 'user_id',
         'quiz_attempts': 'user_id', 'streak_days': 'user_id', 'streak_freezes': 'user_id',
         'reminder_log': 'user_id', 'prefs': 'user_id'}


def assert_schema(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        for table, column in OWNED.items():
            columns = {r[1]: r for r in con.execute(f'PRAGMA table_info({table})')}
            if column not in columns or not columns[column][3]:
                raise AssertionError(f'{table} {column} not NOT NULL')
            foreign_keys = list(con.execute(f'PRAGMA foreign_key_list({table})'))
            if not any(r[2] == 'users' and r[3] == column and r[4] == 'id' for r in foreign_keys):
                raise AssertionError(f'{table}.{column} missing users foreign key')
            indexes = [list(con.execute(f'PRAGMA index_info("{r[1]}")'))
                       for r in con.execute(f'PRAGMA index_list({table})')]
            if not any(index and index[0][2] == column for index in indexes):
                raise AssertionError(f'{table} missing leading {column} index')
        pk = sorted((r[5], r[1]) for r in con.execute('PRAGMA table_info(prefs)') if r[5])
        if [column for _, column in pk] != ['user_id', 'key']:
            raise AssertionError('prefs composite PK missing')
        for table in ('streak_days', 'streak_freezes'):
            pk = {r[1] for r in con.execute(f'PRAGMA table_info({table})') if r[5]}
            if not {'user_id', 'day'} <= pk:
                raise AssertionError(f'{table} composite PK missing')
        for table in ('chapters', 'concepts', 'cards', 'card_drafts'):
            columns = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
            if not columns or columns & {'user_id', 'owner_id'}:
                raise AssertionError(f'{table} missing or has forbidden derived ownership column')
        if list(con.execute('PRAGMA foreign_key_check')):
            raise AssertionError('foreign key violations')
    finally:
        con.close()


if __name__ == '__main__':
    try:
        assert_schema(sys.argv[1])
    except (AssertionError, sqlite3.Error) as exc:
        print('G5 FAIL', exc)
        sys.exit(1)
    print('G5 PASS schema constraints, foreign keys, derived ownership and tenant indexes')
