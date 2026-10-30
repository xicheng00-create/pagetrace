"""Household membership and the one approved shared-book predicate."""


def my_household(con, user_id):
    row = con.execute("SELECT household_id FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        return None
    household_id = row[0] or 1
    con.execute("INSERT OR IGNORE INTO households(id,name,created_at) VALUES(1,'家','2000-01-01T00:00:00+00:00')")
    return con.execute("SELECT * FROM households WHERE id=?", (household_id,)).fetchone()


def member_ids(con, user_id):
    row = con.execute("SELECT household_id FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        return []
    return [r[0] for r in con.execute("SELECT id FROM users WHERE household_id=?", (row[0],))]


def book_visibility_sql(con, user_id, alias="b"):
    """Return a parameterized household owner predicate for a book alias."""
    from services.user_state import ensure_state

    ensure_state(con, user_id)  # REQ-STATE-01：_mine = 当前用户的卡片状态视图
    ids = member_ids(con, user_id)
    if not ids:
        return "1=0", []
    return f"{alias}.owner_id IN ({','.join('?' for _ in ids)})", ids


def new_household(con, name):
    """给自助注册的账号开一间独立家庭（不继承任何人的书架）。"""
    cur = con.execute("INSERT INTO households(name,created_at) VALUES(?,datetime('now'))", (name,))
    return cur.lastrowid


def join_household_of(con, user_id, host_user_id):
    """邀请注册：并入邀请者所在家庭。"""
    row = con.execute("SELECT household_id FROM users WHERE id=?", (host_user_id,)).fetchone()
    if row and row[0]:
        con.execute("UPDATE users SET household_id=? WHERE id=?", (row[0], user_id))
