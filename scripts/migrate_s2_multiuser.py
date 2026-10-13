#!/usr/bin/env python3
"""Idempotent ownership migration. Run on a backed-up DB; production operator executes it.

首次登录用该账号 + 任意 ≥8 位密码完成认领。
账号由 S2_OWNER_USERNAME 指定，默认 owner；没有可用默认密码。"""
import argparse
import os
import shutil
import sqlite3
from pathlib import Path

OWNER = os.environ.get("S2_OWNER_USERNAME", "owner")


def exists(db, table):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def cols(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def ensure_owner_column(db, table, col, uid):
    if not exists(db, table):
        return
    if col not in cols(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {col} INTEGER REFERENCES users(id)")
    db.execute(f"UPDATE {table} SET {col}=? WHERE {col} IS NULL", (uid,))
    # SQLite cannot strengthen an added column; rebuild table preserving its full schema/data.
    info = list(db.execute(f"PRAGMA table_info({table})"))
    if any(row[1] == col and row[3] for row in info):
        return
    if table in ("books", "upload_jobs"):
        rebuild_owner(db, table, col)
    else:
        rebuild_user(db, table, col)


def rebuild_owner(db, table, col):
    if table == "books":
        db.execute("CREATE TABLE books_s2(id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE, title TEXT NOT NULL, slug TEXT NOT NULL, source_path TEXT, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, book_hash TEXT, source TEXT NOT NULL DEFAULT 'kb', owner_id INTEGER NOT NULL REFERENCES users(id), UNIQUE(subject_id,slug))")
        names = [r[1] for r in db.execute("PRAGMA table_info(books)") if r[1] != "owner_id"]
        common = [n for n in names if n in cols(db, 'books_s2')]
        db.execute(f"INSERT INTO books_s2({','.join(common)},owner_id) SELECT {','.join(common)},owner_id FROM books")
        db.execute("DROP TABLE books")
        db.execute("ALTER TABLE books_s2 RENAME TO books")
    else:
        db.execute("CREATE TABLE upload_jobs_s2(id INTEGER PRIMARY KEY, book_hash TEXT NOT NULL, filename TEXT NOT NULL, pages INTEGER NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, owner_id INTEGER NOT NULL REFERENCES users(id))")
        names = [r[1] for r in db.execute("PRAGMA table_info(upload_jobs)") if r[1] != "owner_id"]
        db.execute(f"INSERT INTO upload_jobs_s2({','.join(names)},owner_id) SELECT {','.join(names)},owner_id FROM upload_jobs")
        db.execute("DROP TABLE upload_jobs")
        db.execute("ALTER TABLE upload_jobs_s2 RENAME TO upload_jobs")


def rebuild_user(db, table, col):
    info = list(db.execute(f"PRAGMA table_info({table})"))
    current_pk = [r[1] for r in sorted((r for r in info if r[5]), key=lambda x: x[5])]
    if table in ("streak_days", "streak_freezes"):
        defs = ("day TEXT NOT NULL, target INTEGER NOT NULL, review_done INTEGER NOT NULL, quiz_done INTEGER NOT NULL, met INTEGER NOT NULL, updated_at TEXT NOT NULL" if table == "streak_days" else "day TEXT NOT NULL, streak_kept INTEGER NOT NULL, created_at TEXT NOT NULL")
        db.execute(f"CREATE TABLE {table}_s2(user_id INTEGER NOT NULL REFERENCES users(id),{defs},PRIMARY KEY(user_id,day))")
        names = [r[1] for r in info if r[1] != "user_id"]
        db.execute(f"INSERT INTO {table}_s2(user_id,{','.join(names)}) SELECT user_id,{','.join(names)} FROM {table}")
    elif table == "card_reviews":
        db.execute("CREATE TABLE card_reviews_s2(id INTEGER PRIMARY KEY AUTOINCREMENT,card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,learned_at TEXT NOT NULL,result TEXT NOT NULL,next_review_at TEXT,learn_count INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'learning',user_id INTEGER NOT NULL REFERENCES users(id))")
        db.execute("INSERT INTO card_reviews_s2(id,card_id,learned_at,result,next_review_at,learn_count,status,user_id) SELECT id,card_id,learned_at,result,next_review_at,learn_count,status,user_id FROM card_reviews")
    elif table == "quiz_attempts":
        db.execute("CREATE TABLE quiz_attempts_s2(id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER NOT NULL REFERENCES quiz_items(id) ON DELETE CASCADE,card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,session_id TEXT NOT NULL,my_answer TEXT NOT NULL,is_correct INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,user_id INTEGER NOT NULL REFERENCES users(id))")
        db.execute("INSERT INTO quiz_attempts_s2(id,item_id,card_id,session_id,my_answer,is_correct,created_at,user_id) SELECT id,item_id,card_id,session_id,my_answer,is_correct,created_at,user_id FROM quiz_attempts")
    elif table == "reminder_log":
        db.execute("CREATE TABLE reminder_log_s2(id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT NOT NULL,kind TEXT NOT NULL,sent_at TEXT NOT NULL,user_id INTEGER NOT NULL REFERENCES users(id),UNIQUE(user_id,date,kind))")
        db.execute("INSERT INTO reminder_log_s2(id,date,kind,sent_at,user_id) SELECT id,date,kind,sent_at,user_id FROM reminder_log")
    db.execute(f"DROP TABLE {table}")
    db.execute(f"ALTER TABLE {table}_s2 RENAME TO {table}")


def count(db, table):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def migrate(path):
    path = Path(path).resolve()
    if not path.exists() or not path.is_file():
        raise SystemExit(f"database file missing: {path}")
    backup = path.with_suffix(path.suffix + ".s2.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=OFF")
    tables = ("users", "books", "upload_jobs", "card_reviews", "quiz_attempts", "streak_days", "streak_freezes", "reminder_log", "prefs")
    before = {t: count(db, t) for t in tables if exists(db, t)}
    db.execute("INSERT OR IGNORE INTO users(username,password_hash,role,created_at) VALUES(?,?,?,datetime('now'))", (OWNER, "!BOOTSTRAP_PASSWORD_REQUIRED!", "owner"))
    uid = db.execute("SELECT id FROM users WHERE username=?", (OWNER,)).fetchone()[0]
    db.execute("UPDATE users SET role='owner' WHERE id=?", (uid,))
    for table in ("books", "upload_jobs", "card_reviews", "quiz_attempts", "streak_days", "streak_freezes", "reminder_log"):
        ensure_owner_column(db, table, "owner_id" if table in ("books", "upload_jobs") else "user_id", uid)
    if exists(db, "prefs"):
        if "user_id" not in cols(db, "prefs") or [r[1] for r in sorted((r for r in db.execute("PRAGMA table_info(prefs)") if r[5]), key=lambda x: x[5])] != ["user_id", "key"]:
            old_cols = cols(db, "prefs")
            db.execute("ALTER TABLE prefs RENAME TO prefs_s2_old")
            db.execute("CREATE TABLE prefs(user_id INTEGER NOT NULL REFERENCES users(id),key TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(user_id,key))")
            if "user_id" in old_cols:
                db.execute("INSERT OR IGNORE INTO prefs(user_id,key,value) SELECT user_id,key,value FROM prefs_s2_old")
            else:
                db.execute("INSERT INTO prefs(user_id,key,value) SELECT ?,key,value FROM prefs_s2_old", (uid,))
            db.execute("DROP TABLE prefs_s2_old")
    for t in ("books", "upload_jobs"):
        if exists(db, t): db.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_owner ON {t}(owner_id)")
    for t in ("card_reviews", "quiz_attempts", "streak_days", "streak_freezes", "reminder_log"):
        if exists(db, t): db.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_user ON {t}(user_id)")
    db.commit()
    print(f"backup={backup}")
    for t, n in before.items():
        distcol = "owner_id" if "owner_id" in cols(db, t) else "user_id" if "user_id" in cols(db, t) else None
        dist = dict(db.execute(f"SELECT {distcol},COUNT(*) FROM {t} GROUP BY {distcol}").fetchall()) if distcol else {}
        print(f"{t}: before={n} after={count(db,t)} distribution={dist}")
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    migrate(parser.parse_args().database)
