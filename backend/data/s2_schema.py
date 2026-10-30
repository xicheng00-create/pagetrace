"""新库 S2 schema：字面量 DDL，扫描器逐语句验证，不执行动态构造。"""

FRESH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'owner',
    created_at    TEXT NOT NULL,
    household_id INTEGER NOT NULL DEFAULT 1,
    share_progress INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS households (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
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
    owner_id INTEGER NOT NULL REFERENCES users(id),
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
    status         TEXT NOT NULL DEFAULT 'learning' CHECK (status IN ('new','learning','reviewing','mastered')),
    user_id INTEGER NOT NULL REFERENCES users(id)
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
    user_id INTEGER NOT NULL REFERENCES users(id),
    UNIQUE (user_id, date, kind)
);

CREATE TABLE IF NOT EXISTS prefs (
    user_id INTEGER NOT NULL REFERENCES users(id),
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY(user_id,key)
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
    created_at TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id)
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

CREATE TABLE IF NOT EXISTS video_views (
    user_id    INTEGER NOT NULL REFERENCES users(id),
    video_id   INTEGER NOT NULL REFERENCES card_videos(id) ON DELETE CASCADE,
    day        TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(user_id,video_id,day)
);

CREATE TABLE IF NOT EXISTS streak_days (
    user_id INTEGER NOT NULL REFERENCES users(id),
    day TEXT NOT NULL,
    target      INTEGER NOT NULL,
    review_done INTEGER NOT NULL,
    quiz_done   INTEGER NOT NULL,
    video_done  INTEGER NOT NULL DEFAULT 0,
    video_target INTEGER NOT NULL DEFAULT 5,
    met         INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id,day)
);

CREATE TABLE streak_freezes (
 user_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL,
 streak_kept INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id,day));
CREATE TABLE upload_jobs (
 id INTEGER PRIMARY KEY, book_hash TEXT NOT NULL, filename TEXT NOT NULL,
 pages INTEGER NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
 progress INTEGER NOT NULL DEFAULT 0, error TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 owner_id INTEGER NOT NULL REFERENCES users(id));
CREATE INDEX idx_books_tenant ON books(owner_id);
CREATE INDEX idx_upload_jobs_tenant ON upload_jobs(owner_id);
CREATE INDEX idx_card_reviews_tenant ON card_reviews(user_id);
CREATE INDEX idx_quiz_attempts_tenant ON quiz_attempts(user_id);
CREATE INDEX idx_video_views_tenant ON video_views(user_id);
CREATE INDEX idx_streak_days_tenant ON streak_days(user_id);
CREATE INDEX idx_streak_freezes_tenant ON streak_freezes(user_id);
CREATE INDEX idx_reminder_log_tenant ON reminder_log(user_id);
"""


def fresh_schema():
    """Compatibility accessor for isolated legacy fixtures."""
    return FRESH_SCHEMA
