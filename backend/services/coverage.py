"""覆盖率口径（REQ-FAM-05 / REQ-STATE-01）。"""

from services.household import book_visibility_sql


def household_coverage_counts(con, user_id):
    from services.user_state import ensure_state

    ensure_state(con, user_id)
    clause, params = book_visibility_sql(con, user_id)
    return con.execute(
        "SELECT COUNT(*) total,"
        "SUM(EXISTS(SELECT 1 FROM card_reviews cr WHERE cr.card_id=c.id AND cr.user_id=?)) learned "
        "FROM cards c LEFT JOIN _mine m ON m.card_id=c.id JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id WHERE " + clause,
        (user_id, *params),
    )
