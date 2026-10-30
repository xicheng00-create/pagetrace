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
    ids = member_ids(con, user_id)
    if not ids:
        return "1=0", []
    return f"{alias}.owner_id IN ({','.join('?' for _ in ids)})", ids
