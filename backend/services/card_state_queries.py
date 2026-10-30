"""单卡状态查询（REQ-STATE-01：状态按本人）。"""


def card_status(con, card_id, user_id=None):
    """Return a card only when its book belongs to the user."""
    from services.user_state import ensure_state

    ensure_state(con, user_id)
    return con.execute(
        "SELECT COALESCE(m.status,'new') AS status FROM cards c LEFT JOIN _mine m ON m.card_id=c.id JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE c.id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))", (card_id, user_id)
    )
