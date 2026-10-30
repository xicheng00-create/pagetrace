"""具名卡池查询：测验、答案与调度；cards 统一导出。"""

from services.card_pool_fragments import (  # noqa: F401  （保持既有导入面：_COLS/_FROM 等）
    _COLS,
    _DUE_ORDER,
    _DUE_TAIL,
    _FROM,
    _NEW_TAIL,
    _PRIORITY,
)


def learned_quiz_cards(con, subject_id, book_ids, user_id):
    """services/quiz._quiz_pool: preserve original pool SQL and bindings."""
    where, params = "", []
    if subject_id:
        where += " AND c.subject_id=?"
        params.append(subject_id)
    if book_ids is not None:
        if book_ids:
            marks = ','.join('?' for _ in book_ids)
            where += f" AND b.id IN ({marks})"
            params.extend(book_ids)
        else:
            where += " AND 0"
    return con.execute(
        "SELECT c.id AS card_id, cp.chapter_id AS chapter_id, c.front, c.back, c.status,"
        " c.learn_count, c.next_review_at,"
        "cp.name AS concept, ch.name AS chapter, b.title AS book, s.name AS subject "
        "FROM cards c JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id "
        "JOIN books b ON b.id=ch.book_id JOIN subjects s ON s.id=c.subject_id "
        "WHERE b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) AND ch.unlocked_at IS NOT NULL AND c.status <> 'new'" + where,
        [user_id, *params],
    )


def card_answer(con, card_id, user_id=None):
    """Return the answer only for a card owned by the current user."""
    return con.execute(
        "SELECT c.front, c.back FROM cards c JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE c.id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))", (card_id, user_id)
    )


def wrong_answer_cards(con, user_id):
    """按用户列出错题，并将关联子查询限制在同一用户数据中。"""
    return con.execute(
        "SELECT qa.card_id,COUNT(*) wrong_count,c.front,c.status,"
        "(SELECT qi.stem FROM quiz_attempts x JOIN quiz_items qi ON qi.id=x.item_id WHERE x.card_id=qa.card_id AND x.user_id=? AND x.is_correct=0 ORDER BY x.id DESC LIMIT 1) stem,"
        "(SELECT qi.answer_key FROM quiz_attempts x JOIN quiz_items qi ON qi.id=x.item_id WHERE x.card_id=qa.card_id AND x.user_id=? AND x.is_correct=0 ORDER BY x.id DESC LIMIT 1) correct_answer,"
        "(SELECT x.my_answer FROM quiz_attempts x WHERE x.card_id=qa.card_id AND x.user_id=? AND x.is_correct=0 ORDER BY x.id DESC LIMIT 1) my_answer "
        "FROM quiz_attempts qa JOIN cards c ON c.id=qa.card_id JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE qa.is_correct=0 AND qa.user_id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) GROUP BY qa.card_id "
        "ORDER BY wrong_count DESC,qa.card_id ASC",
        (user_id, user_id, user_id, user_id, user_id),
    )


def chapter_answer_pool(con, chapter_id, exclude_card_id, user_id=None):
    """Return same-book distractors only for the current user's book."""
    return con.execute(
        "SELECT c.back FROM cards c JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE cp.chapter_id=? AND c.id<>? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))",
        (chapter_id, exclude_card_id, user_id),
    )


def card_content_hash(con, card_id, user_id=None):
    """Return content hash only for a card owned by the current user."""
    return con.execute(
        "SELECT c.content_hash FROM cards c JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE c.id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))", (card_id, user_id)
    )


def current_cached_quiz_item(con, card_id, user_id):
    """Return a quiz item only when the card belongs to the user."""
    return con.execute(
        "SELECT qi.*, (SELECT COUNT(*) FROM quiz_attempts qa WHERE qa.item_id=qi.id AND qa.user_id=?) AS answered"
        " FROM quiz_items qi JOIN cards c ON c.id=qi.card_id"
        " JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id"
        " WHERE qi.card_id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) AND qi.card_content_hash = c.content_hash"
        " ORDER BY answered ASC, qi.id ASC LIMIT 1",
        (user_id, card_id, user_id),
    )


def quiz_card_context(con, card_id, user_id):
    """services/quizgen.card_context: preserve original pool SQL and bindings."""
    return con.execute(
        "SELECT c.id AS card_id, c.front, c.back, cp.chapter_id, cp.name AS concept,"
        " ch.name AS chapter, b.title AS book"
        " FROM cards c JOIN concepts cp ON cp.id=c.concept_id"
        " JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id"
        " WHERE c.id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))",
        (card_id, user_id),
    )


def weak_chapter_card_rows(con, since_utc, user_id):
    """services/report.weak_chapters: preserve original pool SQL and bindings."""
    where = "WHERE qa.is_correct = 0 AND qa.user_id = ?"
    params = [user_id]
    if since_utc:
        where += " AND qa.created_at >= ?"
        params.append(since_utc)
    return con.execute(
        "SELECT ch.id AS chapter_id, ch.name AS chapter, b.title AS book,"
        " s.name AS subject, qa.card_id, c.front, COUNT(*) AS wrong_count"
        " FROM quiz_attempts qa"
        " JOIN cards c ON c.id = qa.card_id"
        " JOIN concepts cp ON cp.id = c.concept_id"
        " JOIN chapters ch ON ch.id = cp.chapter_id"
        " JOIN books b ON b.id = ch.book_id"
        " JOIN subjects s ON s.id = b.subject_id"
        f" {where} AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))"
        " GROUP BY ch.id, qa.card_id"
        " ORDER BY ch.id ASC, wrong_count DESC, qa.card_id ASC",
        [*params, user_id],
    )


def update_card_schedule(con, card_id, lc, nxt, status, user_id):
    """services/review_sched.apply_result: preserve original pool SQL and bindings."""
    return con.execute(
        "UPDATE cards SET status=?, learn_count=?, next_review_at=? WHERE id=? AND concept_id IN "
        "(SELECT cp.id FROM concepts cp JOIN chapters ch ON ch.id=cp.chapter_id "
        "JOIN books b ON b.id=ch.book_id WHERE b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)))", (status, lc, nxt, card_id, user_id)
    )


def card_schedule(con, card_id, user_id):
    """services/review_sched.apply_result: preserve original pool SQL and bindings."""
    return con.execute(
        "SELECT c.id,c.status,c.learn_count,c.next_review_at FROM cards c "
        "JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id "
        "JOIN books b ON b.id=ch.book_id WHERE c.id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))", (card_id, user_id))




def available_due_count(con, at_iso, book_ids, day_start_iso, user_id=None):
    """Count due cards in books owned by the current user."""
    clause, bparams = "", []
    if book_ids is not None:
        if book_ids:
            marks = ','.join('?' for _ in book_ids)
            clause = f" AND ch.book_id IN ({marks})"
            bparams = list(book_ids)
        else:
            clause = " AND 0"
    return con.execute(
        "SELECT COUNT(*) FROM cards c JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) AND ch.unlocked_at IS NOT NULL" + clause + " AND ("
        "(c.status <> 'new' AND c.next_review_at IS NOT NULL AND c.next_review_at <= ?) "
        "OR EXISTS (SELECT 1 FROM card_reviews cr WHERE cr.card_id=c.id AND cr.user_id=? AND cr.learned_at >= ?))",
        [user_id, *bparams, at_iso, user_id, day_start_iso],
    )


def available_new_count(con, book_ids, user_id=None):
    """Count new cards in books owned by the current user."""
    clause, bparams = "", []
    if book_ids is not None:
        if book_ids:
            marks = ','.join('?' for _ in book_ids)
            clause = f" AND ch.book_id IN ({marks})"
            bparams = list(book_ids)
        else:
            clause = " AND 0"
    return con.execute(
        "SELECT COUNT(*) FROM cards c JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) AND ch.unlocked_at IS NOT NULL AND c.status='new'" + clause,
        [user_id, *bparams],
    )


def chapter_pool_counts(con, at, chapter_id, user_id=None):
    """services/unlock.chapter_stats: restrict derived chapter to book owner."""
    return con.execute(
        "SELECT SUM(CASE WHEN c.status <> 'new' THEN 1 ELSE 0 END) AS learned,"
        " SUM(CASE WHEN c.status = 'mastered' THEN 1 ELSE 0 END) AS mastered,"
        " SUM(CASE WHEN c.status <> 'new' AND c.next_review_at IS NOT NULL AND c.next_review_at <= ? THEN 1 ELSE 0 END) AS due,"
        " COUNT(*) AS total FROM cards c JOIN concepts cp ON cp.id=c.concept_id"
        " JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id"
        " WHERE cp.chapter_id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))", (at, chapter_id, user_id)
    )
