"""Tutor 四表 DDL（规格 v0.1 §8）：conversations / messages / tutor_actions / quota_usage。

幂等；由 `data.models.migrate()` 调用 —— 新库（FRESH_SCHEMA）与既有库（SCHEMA）走同一条建表路径，
不手工改库。多租户口径：conversations / tutor_actions / quota_usage 带 `user_id` 与前导索引；
messages 只经 `conversation_id` 归属（同一会话不会有两个 owner，避免身份两处各说各话）。
"""


def ensure(con) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS conversations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " user_id INTEGER NOT NULL REFERENCES users(id),"
        " title TEXT NOT NULL DEFAULT '',"
        " summary TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " deleted_at TEXT)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,"
        " role TEXT NOT NULL CHECK (role IN ('user','assistant')),"
        " content TEXT NOT NULL,"
        " tokens_in INTEGER,"
        " tokens_out INTEGER,"
        " created_at TEXT NOT NULL)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS tutor_actions ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,"
        " user_id INTEGER NOT NULL REFERENCES users(id),"
        " type TEXT NOT NULL CHECK (type IN ('add_card','reschedule','set_daily_goal')),"
        " payload_json TEXT NOT NULL,"
        " reason TEXT,"
        " status TEXT NOT NULL DEFAULT 'pending'"
        "   CHECK (status IN ('pending','confirmed','dismissed','expired')),"
        " created_at TEXT NOT NULL,"
        " resolved_at TEXT,"
        " resolved_by INTEGER REFERENCES users(id))"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS quota_usage ("
        " user_id INTEGER NOT NULL REFERENCES users(id),"
        " day TEXT NOT NULL,"
        " chat_calls INTEGER NOT NULL DEFAULT 0,"
        " tokens_in INTEGER NOT NULL DEFAULT 0,"
        " tokens_out INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY (user_id, day))"
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_conversations_tenant ON conversations(user_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_tutor_actions_tenant ON tutor_actions(user_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)")
