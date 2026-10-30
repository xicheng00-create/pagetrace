"""卡池唯一入口：具名用途查询；SQL、绑定参数与排序保持原样。"""

from __future__ import annotations

from datetime import datetime, timedelta

from config import BaseConfig

from services.card_quiz_pool import (  # noqa: F401  # noqa: F401
    _COLS,
    _DUE_ORDER,
    _DUE_TAIL,
    _FROM,
    _NEW_TAIL,
    _PRIORITY,
    available_due_count,
    available_new_count,
    card_answer,
    card_content_hash,
    card_schedule,
    chapter_answer_pool,
    chapter_pool_counts,
    current_cached_quiz_item,
    learned_quiz_cards,
    quiz_card_context,
    update_card_schedule,
    weak_chapter_card_rows,
    wrong_answer_cards,
)
from services.clock import TZ8, now
from services.household import book_visibility_sql


def due_query(
    subject_id: int | None = None,
    book_ids: list[int] | None = None,
    user_id: int | None = None,
    con=None,
) -> tuple[str, list]:
    """Build due queue query constrained by the book owner."""
    from services.scope import book_filter

    parts, params = [], []
    if user_id is not None:
        clause, values = book_visibility_sql(con, user_id)
        parts.append(clause)
        params.extend(values)
    if subject_id:
        parts.append("s.id = ?")
        params.append(subject_id)
    clause, bparams = book_filter(book_ids, "b.id")
    if clause:
        parts.append(clause.removeprefix(" AND "))
        params.extend(bparams)
    sub = (" AND " + " AND ".join(parts)) if parts else ""
    return f"SELECT {_COLS}{_FROM}{sub}{_DUE_TAIL}", params


def new_query(
    subject_id: int | None = None,
    book_ids: list[int] | None = None,
    user_id: int | None = None,
    con=None,
) -> tuple[str, list]:
    """Build new-card query constrained by the book owner."""
    from services.scope import book_filter

    parts, params = [], []
    if user_id is not None:
        clause, values = book_visibility_sql(con, user_id)
        parts.append(clause)
        params.extend(values)
    if subject_id:
        parts.append("s.id = ?")
        params.append(subject_id)
    clause, bparams = book_filter(book_ids, "b.id")
    if clause:
        parts.append(clause.removeprefix(" AND "))
        params.extend(bparams)
    sub = (" AND " + " AND ".join(parts)) if parts else ""
    return f"SELECT {_COLS}{_FROM}{sub}{_NEW_TAIL}", params


def today_queue(
    con,
    *,
    at: str | None = None,
    target: int | None = None,
    batch_max: int | None = None,
    new_max: int | None = None,
    subject_id: int | None = None,
    book_ids: list[int] | None = None,
    extra: bool = False,
    user_id=None,
) -> dict:
    """返回 {"due": [...], "new": [...]}；两组均为已解锁章内的卡，合计 = min(target, 可用)。

    `target`（GOAL-001）= 队列上限（缺省 `REVIEW_TASK_TARGET`）；`extra` 只表语义（同口径）。
    `book_ids` = 图书范围（SCOPE-001：None=全部；[]=空；否则只在这些书内）。
    """
    if user_id is None:
        from flask import g

        user_id = g.user_id
    target = BaseConfig.REVIEW_TASK_TARGET if target is None else int(target)
    batch_max = BaseConfig.REVIEW_BATCH_MAX if batch_max is None else batch_max
    new_max = BaseConfig.NEW_CARDS_BATCH_MAX if new_max is None else new_max
    at_dt = datetime.fromisoformat(at) if isinstance(at, str) else at
    if at_dt is None:
        at_dt = now()
    at_dt = at_dt.replace(tzinfo=TZ8) if at_dt.tzinfo is None else at_dt.astimezone(TZ8)
    start = at_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    start_s, end_s = start.isoformat(), end.isoformat()
    done = 0
    if not extra:
        done = con.execute(
            "SELECT COUNT(*) FROM (SELECT cr.card_id, cr.result, "
            "ROW_NUMBER() OVER (PARTITION BY cr.card_id ORDER BY cr.learned_at DESC, cr.id DESC) rn "
            "FROM card_reviews cr WHERE cr.user_id=? AND cr.learned_at>=? AND cr.learned_at<?) latest "
            "JOIN cards c ON c.id=latest.card_id "
            "WHERE latest.rn=1 AND latest.result IN ('hard','good') AND c.next_review_at>?",
            (user_id, start_s, end_s, at_dt.isoformat()),
        ).fetchone()[0]
    cap = min(max(target - done, 0) if not extra else target, batch_max)

    exclusion = (
        " AND c.id NOT IN (SELECT cr.card_id FROM card_reviews cr "
        "WHERE cr.user_id=? AND cr.learned_at>=? AND cr.learned_at<? AND cr.result IN ('hard','good') "
        "AND c.next_review_at>?)"
    )
    due_sql, due_head = due_query(subject_id, book_ids, user_id, con)
    due_sql = due_sql.replace(" AND c.status <> 'new'", exclusion + " AND c.status <> 'new'")
    due_sql = due_sql.replace(_DUE_ORDER, f" ORDER BY {_PRIORITY}, c.next_review_at ASC, c.id ASC LIMIT ?")
    due = [
        dict(r)
        for r in con.execute(
            due_sql,
            [*due_head, user_id, start_s, end_s, at_dt.isoformat(), at_dt.isoformat(), user_id, start.date().isoformat(), cap],
        ).fetchall()
    ]

    remaining = max(cap - len(due), 0)
    limit = min(remaining, new_max)
    new: list[dict] = []
    if limit > 0:
        new_sql, new_head = new_query(subject_id, book_ids, user_id, con)
        new_sql = new_sql.replace(" AND c.status = 'new'", exclusion + " AND c.status = 'new'")
        new = [
            dict(r)
            for r in con.execute(
                new_sql, [*new_head, user_id, start_s, end_s, at_dt.isoformat(), limit]
            ).fetchall()
        ]
    return {
        "due": due,
        "new": new,
        "group": {"target": target, "done": done, "remaining": max(target - done, 0)},
    }


def household_coverage_counts(con, user_id):
    clause, params = book_visibility_sql(con, user_id)
    return con.execute(
        "SELECT COUNT(*) total,SUM(c.status<>'new') learned FROM cards c "
        "JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id "
        "JOIN books b ON b.id=ch.book_id WHERE " + clause,
        params,
    )


def books_with_pool_counts(con, sid, user_id):
    """api/books.list_books: preserve original pool SQL and bindings."""
    clause, scope_params = book_visibility_sql(con, user_id)
    return con.execute(
        "SELECT b.id, b.title, b.slug, b.status,"
        " (SELECT COUNT(*) FROM chapters ch WHERE ch.book_id=b.id) AS chapters_total,"
        " (SELECT COUNT(*) FROM chapters ch WHERE ch.book_id=b.id"
        "     AND ch.unlocked_at IS NOT NULL) AS chapters_unlocked,"
        " (SELECT COALESCE(MAX(ch.order_no),0) FROM chapters ch WHERE ch.book_id=b.id"
        "     AND ch.unlocked_at IS NOT NULL) AS unlocked_upto,"
        " (SELECT COUNT(*) FROM cards c WHERE c.subject_id=b.subject_id"
        "     AND c.concept_id IN (SELECT id FROM concepts WHERE chapter_id IN"
        "         (SELECT id FROM chapters WHERE book_id=b.id))) AS cards_total,"
        " (SELECT COUNT(*) FROM cards c WHERE c.status<>'new' AND c.concept_id IN"
        "         (SELECT id FROM concepts WHERE chapter_id IN"
        "             (SELECT id FROM chapters WHERE book_id=b.id))) AS learned,"
        " (SELECT COUNT(*) FROM cards c WHERE c.status='mastered' AND c.concept_id IN"
        "         (SELECT id FROM concepts WHERE chapter_id IN"
        "             (SELECT id FROM chapters WHERE book_id=b.id))) AS mastered "
        "FROM books b WHERE b.subject_id=? AND " + clause + " ORDER BY b.id",
        (sid, *scope_params),
    )


def cards_for_concept(con, cid, user_id):
    """Return cards visible in the current household."""
    clause, params = book_visibility_sql(con, user_id)
    return con.execute(
        "SELECT c.id,c.title,c.front,c.back,c.source,c.status,c.learn_count,c.next_review_at "
        "FROM cards c JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE c.concept_id=? AND " + clause + " ORDER BY c.id",
        (cid, *params),
    )


def concept_status_counts(con, chid, user_id=None):
    """Return card states only for a chapter owned by the current user."""
    sql = (
        "SELECT c.concept_id, c.status, COUNT(*) AS n FROM cards c "
        "JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id "
        "JOIN books b ON b.id=ch.book_id WHERE ch.id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) "
        "GROUP BY c.concept_id, c.status"
    )
    return con.execute(sql, (chid, user_id))


def concepts_with_card_counts(con, chid, user_id=None):
    """Return concepts and counts only for a chapter owned by the current user."""
    return con.execute(
        "SELECT cp.id, cp.name, cp.source_pages, cp.confidence, cp.tags, "
        "(SELECT COUNT(*) FROM cards c WHERE c.concept_id=cp.id) AS cards_total "
        "FROM concepts cp JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE cp.chapter_id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) ORDER BY cp.id",
        (chid, user_id),
    )


def scheduled_plan_cards(con, at_iso, user_id):
    """services/plan.plan_items: preserve original pool SQL and bindings."""
    return con.execute(
        "SELECT c.id AS card_id, c.front, c.status, c.next_review_at, c.title,"
        " cp.name AS concept, ch.name AS chapter, b.title AS book"
        " FROM cards c"
        " JOIN concepts cp ON cp.id = c.concept_id"
        " JOIN chapters ch ON ch.id = cp.chapter_id"
        " JOIN books b ON b.id = ch.book_id"
        " WHERE c.status <> 'new' AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))"
        " ORDER BY CASE WHEN c.next_review_at IS NULL THEN 2"
        "               WHEN c.next_review_at <= ? THEN 0 ELSE 1 END ASC,"
        "          c.next_review_at ASC, c.id ASC",
        (user_id, at_iso),
    )


def card_status(con, card_id, user_id=None):
    """Return a card only when its book belongs to the user."""
    return con.execute(
        "SELECT c.status FROM cards c JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE c.id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))", (card_id, user_id)
    )


def level_card_statuses(con, user_id, *, book_id=None, chapter_id=None, subject_id=None):
    """Return derived card statuses only from books owned by user."""
    return con.execute(
        "SELECT c.id, c.status FROM cards c JOIN concepts cp ON cp.id=c.concept_id "
        "JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id "
        "WHERE b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) AND (? IS NULL OR ch.book_id=?) "
        "AND (? IS NULL OR cp.chapter_id=?) AND (? IS NULL OR c.subject_id=?)",
        (user_id, book_id, book_id, chapter_id, chapter_id, subject_id, subject_id),
    )


def subject_pool_counts(con, at, subject, user_id):
    """当前租户学科卡池计数。"""
    return con.execute(
        "SELECT COUNT(*) total,SUM(c.status='new') unlearned,"
        "SUM(c.status<>'new' AND c.next_review_at IS NOT NULL AND c.next_review_at<=?) due "
        "FROM cards c JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id "
        "JOIN books b ON b.id=ch.book_id WHERE c.subject_id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))",
        (at, subject['id'], user_id),
    )


def subject_last_review(con, subject, user_id):
    """services/progress.subject_metrics: preserve original pool SQL and bindings."""
    return con.execute(
        "SELECT MAX(cr.learned_at) FROM card_reviews cr JOIN cards c ON c.id=cr.card_id JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id WHERE c.subject_id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) AND cr.user_id=?",
        (subject["id"], user_id, user_id),
    )


