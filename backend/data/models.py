"""表结构（DESIGN_SPEC §4）。SCHEMA 幂等；migrate() 只做向后兼容的加列/建索引。

铁律：表结构变更写这里（幂等 SQL），不手工改库；生产库 data-local/review.sqlite3。
"""
from datetime import UTC, datetime, timedelta, timezone

from config import BaseConfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'owner',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_hash TEXT NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    used_by INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS subjects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL UNIQUE,
    order_no   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id  INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    slug        TEXT NOT NULL,
    source_path TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL,
    UNIQUE (subject_id, slug)
);

CREATE TABLE IF NOT EXISTS chapters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    order_no    INTEGER NOT NULL DEFAULT 0,
    anchor      TEXT NOT NULL,
    unlocked_at TEXT,
    status      TEXT NOT NULL DEFAULT 'locked',
    UNIQUE (book_id, anchor)
);

CREATE TABLE IF NOT EXISTS concepts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_uid  TEXT NOT NULL UNIQUE,
    chapter_id   INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    source_pages TEXT,
    confidence   TEXT,
    tags         TEXT
);

CREATE TABLE IF NOT EXISTS cards (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id     INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    subject_id     INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    front          TEXT NOT NULL,
    back           TEXT NOT NULL,
    source         TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','learning','reviewing','mastered')),
    learn_count    INTEGER NOT NULL DEFAULT 0,
    next_review_at TEXT,
    created_at     TEXT NOT NULL,
    title          TEXT,
    UNIQUE (concept_id, content_hash)
);

CREATE TABLE IF NOT EXISTS card_reviews (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id        INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    learned_at     TEXT NOT NULL,
    result         TEXT NOT NULL,
    next_review_at TEXT,
    learn_count    INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'learning' CHECK (status IN ('new','learning','reviewing','mastered'))
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id       INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    book_id          INTEGER REFERENCES books(id) ON DELETE SET NULL,
    new_count        INTEGER NOT NULL DEFAULT 0,
    merged_count     INTEGER NOT NULL DEFAULT 0,
    skipped_count    INTEGER NOT NULL DEFAULT 0,
    rejected_count   INTEGER NOT NULL DEFAULT 0,
    contract_version INTEGER NOT NULL DEFAULT 1,
    started_at       TEXT NOT NULL,
    finished_at      TEXT
);

CREATE TABLE IF NOT EXISTS reminder_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    date    TEXT NOT NULL,
    kind    TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    UNIQUE (date, kind)
);

CREATE TABLE IF NOT EXISTS prefs (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id      INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    type         TEXT NOT NULL CHECK (type IN ('choice','bool')),
    stem         TEXT NOT NULL,
    options      TEXT NOT NULL,              -- JSON 数组（响应不给前端，仅服务端判分用）
    answer_key   TEXT NOT NULL,
    points       INTEGER NOT NULL DEFAULT 1,
    source       TEXT NOT NULL CHECK (source IN ('ai','fallback')),
    content_hash TEXT NOT NULL UNIQUE,
    card_content_hash TEXT,                  -- 出题时该卡 front/back 的 content_hash（QUIZ-011：卡文变化 → 重生）
    model        TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL REFERENCES quiz_items(id) ON DELETE CASCADE,
    card_id    INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    my_answer  TEXT NOT NULL,
    is_correct INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quiz_items_card   ON quiz_items(card_id);
CREATE INDEX IF NOT EXISTS idx_quiz_items_hash   ON quiz_items(content_hash);
CREATE INDEX IF NOT EXISTS idx_quiz_attempt_item ON quiz_attempts(item_id);
CREATE INDEX IF NOT EXISTS idx_quiz_attempt_card ON quiz_attempts(card_id);
CREATE INDEX IF NOT EXISTS idx_quiz_attempt_sess ON quiz_attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_books_subject       ON books(subject_id);
CREATE INDEX IF NOT EXISTS idx_chapters_book       ON chapters(book_id, order_no);
CREATE INDEX IF NOT EXISTS idx_concepts_chapter    ON concepts(chapter_id);
CREATE INDEX IF NOT EXISTS idx_cards_concept       ON cards(concept_id);
CREATE INDEX IF NOT EXISTS idx_cards_subject       ON cards(subject_id);
CREATE INDEX IF NOT EXISTS idx_reviews_card        ON card_reviews(card_id);
CREATE INDEX IF NOT EXISTS idx_reviews_next        ON card_reviews(next_review_at);

CREATE TABLE IF NOT EXISTS streak_days (
    day         TEXT PRIMARY KEY,
    target      INTEGER NOT NULL,
    review_done INTEGER NOT NULL,
    quiz_done   INTEGER NOT NULL,
    met         INTEGER NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def _ensure_column(con, table, column, definition):
    if column not in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate_upload(con):
    """UP-010：不改任何 cards / review / quiz 历史。"""
    _ensure_column(con, 'books', 'book_hash', 'TEXT')
    _ensure_column(con, 'books', 'source', "TEXT NOT NULL DEFAULT 'kb'")
    conflicts = con.execute("SELECT id,book_hash FROM books WHERE book_hash IN "
                            "(SELECT book_hash FROM books WHERE book_hash IS NOT NULL "
                            "GROUP BY book_hash HAVING COUNT(*)>1) ORDER BY id").fetchall()
    if conflicts:
        print('book_hash 冲突行:', [tuple(row) for row in conflicts])
        raise ValueError('重复非 NULL book_hash，迁移中止')
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_books_hash ON books(book_hash)')
    con.execute("""CREATE TABLE IF NOT EXISTS upload_jobs (
        id INTEGER PRIMARY KEY, book_hash TEXT NOT NULL, filename TEXT NOT NULL,
        pages INTEGER NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
        progress INTEGER NOT NULL DEFAULT 0, error TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS card_drafts (
        id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES upload_jobs(id),
        book_hash TEXT NOT NULL, payload TEXT NOT NULL, confidence TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'kept', created_at TEXT NOT NULL)""")


def migrate(con) -> None:  # pragma: no cover
    """向后兼容迁移：只允许「加列 / 建索引」，不许删列改名。

    新增迁移请追加为幂等的 `ALTER TABLE ... ADD COLUMN`，并先查 PRAGMA table_info
    判断列是否已存在（SQLite 无 IF NOT EXISTS 的加列语法）。
    """
    cols = {r[1] for r in con.execute("PRAGMA table_info(cards)").fetchall()}
    if "learn_count" not in cols:
        con.execute("ALTER TABLE cards ADD COLUMN learn_count INTEGER NOT NULL DEFAULT 0")
    if "next_review_at" not in cols:
        con.execute("ALTER TABLE cards ADD COLUMN next_review_at TEXT")
    # CARD-007：契约 `title`（「概念名 · 子卡短名」复合格式）逐字落库；既有行由幂等重导回填。
    if "title" not in cols:
        con.execute("ALTER TABLE cards ADD COLUMN title TEXT")
    quiz_cols = {r[1] for r in con.execute("PRAGMA table_info(quiz_items)").fetchall()}
    if "card_content_hash" not in quiz_cols:
        con.execute("ALTER TABLE quiz_items ADD COLUMN card_content_hash TEXT")
    # 回填既有题目的卡文 content_hash（出题时卡文的指纹；卡文变化 → 下次复用即失效重生，QUIZ-011）
    con.execute(
        "UPDATE quiz_items SET card_content_hash ="
        " (SELECT c.content_hash FROM cards c WHERE c.id = quiz_items.card_id)"
        " WHERE card_content_hash IS NULL")
    con.execute("CREATE TABLE IF NOT EXISTS streak_freezes (day TEXT PRIMARY KEY, streak_kept INTEGER NOT NULL, created_at TEXT NOT NULL)")
    # Snapshot history is deliberately evidence-only: never infer old availability.
    con.execute("CREATE TABLE IF NOT EXISTS streak_days (day TEXT PRIMARY KEY, target INTEGER NOT NULL, review_done INTEGER NOT NULL, quiz_done INTEGER NOT NULL, met INTEGER NOT NULL, updated_at TEXT NOT NULL)")
    # 用户偏好（SCOPE-001~003）：图书复习范围等键值对；老库补建（幂等）。
    con.execute("CREATE TABLE IF NOT EXISTS prefs (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    # SCOPE-003（修订 v0.11.0）：空范围不再是合法状态——幂等删除历史遗留的 `book_scope="[]"` 脏行。
    con.execute("DELETE FROM prefs WHERE key='book_scope' AND value='[]'")
    tz = timezone(timedelta(hours=BaseConfig.STREAK_TZ_OFFSET_HOURS))
    today = datetime.fromtimestamp(__import__('time').time(), tz).date()
    switch = datetime.fromisoformat(BaseConfig.STREAK_GOAL_FROM_DATE).date()
    reviews = {}
    for row in con.execute("SELECT learned_at FROM card_reviews WHERE learned_at IS NOT NULL"):
        try:
            dt = datetime.fromisoformat(str(row[0]))
            dt = dt if dt.tzinfo else dt.replace(tzinfo=tz)
            local_day = dt.astimezone(tz).date()
            reviews[local_day] = reviews.get(local_day, 0) + 1
        except (TypeError, ValueError):
            continue
    for day in sorted(reviews):
        if day >= today:
            continue
        if day < switch:
            met = 1
        else:
            met = int(_migration_counts(con, day, tz, BaseConfig))
        con.execute("INSERT OR IGNORE INTO streak_days(day,target,review_done,quiz_done,met,updated_at) VALUES(?,?,?,?,?,?)",
                    (day.isoformat(), BaseConfig.REVIEW_TASK_TARGET, reviews[day], _migration_quizzes(con, day, tz), met, datetime.fromtimestamp(__import__('time').time(), tz).isoformat(timespec="seconds")))


def _migration_quizzes(con, day, tz):  # pragma: no cover
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz).astimezone(UTC).isoformat()
    end = (datetime.combine(day, datetime.min.time(), tzinfo=tz) + timedelta(days=1)).astimezone(UTC).isoformat()
    return con.execute("SELECT COUNT(DISTINCT item_id) FROM quiz_attempts WHERE created_at>=? AND created_at<?", (start, end)).fetchone()[0]


def _migration_counts(con, day, tz, config):  # pragma: no cover
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=1)
    reviews = con.execute("SELECT COUNT(DISTINCT card_id) FROM card_reviews WHERE learned_at>=? AND learned_at<?", (start.isoformat(), end.isoformat())).fetchone()[0]
    return reviews >= config.REVIEW_TASK_TARGET and _migration_quizzes(con, day, tz) >= config.QUIZ_TASK_TARGET
