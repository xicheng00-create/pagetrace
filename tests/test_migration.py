import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from data.models import SCHEMA, migrate, migrate_upload


def test_migration_idempotent():
    con = sqlite3.connect(':memory:')
    con.executescript(SCHEMA)
    con.execute('ALTER TABLE books ADD COLUMN book_hash TEXT')
    migrate(con)
    migrate(con)
    assert 'learn_count' in {r[1] for r in con.execute('PRAGMA table_info(cards)')}
    assert not con.execute("SELECT name FROM sqlite_master WHERE name='uq_books_hash'").fetchone()
    assert not con.execute("SELECT name FROM sqlite_master WHERE name='upload_jobs'").fetchone()
    assert not con.execute("SELECT name FROM sqlite_master WHERE name='card_drafts'").fetchone()


def test_startup_migration_excludes_upload_ddl():
    con = sqlite3.connect(':memory:')
    con.executescript(SCHEMA)
    migrate(con)
    objects = {row[0] for row in con.execute("SELECT name FROM sqlite_master")}
    assert not ({'upload_jobs', 'card_drafts', 'uq_books_hash'} & objects)


def test_explicit_upload_migration_is_idempotent():
    con = sqlite3.connect(':memory:')
    con.executescript(SCHEMA)
    migrate_upload(con)
    before = con.iterdump().__next__() if False else [tuple(r) for r in con.execute("SELECT type,name,sql FROM sqlite_master WHERE name IN ('upload_jobs','card_drafts','uq_books_hash') ORDER BY name")]
    migrate_upload(con)
    after = [tuple(r) for r in con.execute("SELECT type,name,sql FROM sqlite_master WHERE name IN ('upload_jobs','card_drafts','uq_books_hash') ORDER BY name")]
    assert set(name for _, name, _ in after) == {'upload_jobs', 'card_drafts', 'uq_books_hash'}
    assert after == before


def test_existing_progress_preserved():
    con = sqlite3.connect(':memory:')
    con.executescript(SCHEMA)
    for i in range(394):
        con.execute("INSERT INTO card_reviews(card_id,learned_at,result) VALUES(1,?,'good')", (f'2026-10-01T08:{i % 60:02}:00+08:00',))
    for i in range(110):
        con.execute("INSERT INTO quiz_attempts(item_id,card_id,session_id,my_answer,created_at) VALUES(1,1,'s','yes',?)", (f'2026-10-01T00:{i % 60:02}:00+00:00',))

    def fingerprint():
        return [(con.execute(f'SELECT COUNT(*), MAX({column}) FROM {table}').fetchone(),
                 hashlib.sha256(repr(con.execute(f'SELECT * FROM {table} ORDER BY id LIMIT 20').fetchall()).encode()).hexdigest())
                for table, column in [('card_reviews', 'learned_at'), ('quiz_attempts', 'created_at')]]
    before = fingerprint()
    migrate_upload(con)
    migrate_upload(con)
    assert fingerprint() == before


def test_pm_migration_script_backup_and_dry_run(tmp_path, monkeypatch, capsys):
    from scripts.migrate_upload import main, run
    path = tmp_path / 'db.sqlite3'
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
    before = path.read_bytes()
    assert run(path)['dry_run']
    assert path.read_bytes() == before
    result = run(path, True)
    assert Path(result['backup']).exists()
    assert result['before'] == result['after']
    monkeypatch.setattr(sys, 'argv', ['migrate_upload', str(path)])
    main()
    assert 'dry_run' in capsys.readouterr().out


def test_duplicate_hash_abort_prints_conflicts(capsys):
    con = sqlite3.connect(':memory:')
    con.executescript(SCHEMA)
    con.execute('ALTER TABLE books ADD COLUMN book_hash TEXT')
    for slug in ('a', 'b'):
        con.execute("INSERT INTO books(subject_id,title,slug,created_at,book_hash) VALUES(1,'B',?,'now','same')", (slug,))
    with pytest.raises(ValueError, match='迁移中止'):
        migrate_upload(con)
    assert 'same' in capsys.readouterr().out
    assert not con.execute("SELECT name FROM sqlite_master WHERE name='uq_books_hash'").fetchone()
