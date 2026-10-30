"""migrate() 用到的日期区间计数（从 models.py 拆出，满足单文件 <300 行）。"""

from datetime import UTC, datetime, timedelta


def _migration_quizzes(con, day, tz):  # pragma: no cover
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz).astimezone(UTC).isoformat()
    end = (
        (datetime.combine(day, datetime.min.time(), tzinfo=tz) + timedelta(days=1))
        .astimezone(UTC)
        .isoformat()
    )
    return con.execute(
        "SELECT COUNT(DISTINCT item_id) FROM quiz_attempts WHERE created_at>=? AND created_at<?", (start, end)
    ).fetchone()[0]


def _migration_counts(con, day, tz, config):  # pragma: no cover
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=1)
    reviews = con.execute(
        "SELECT COUNT(DISTINCT card_id) FROM card_reviews WHERE learned_at>=? AND learned_at<?",
        (start.isoformat(), end.isoformat()),
    ).fetchone()[0]
    return (
        reviews >= config.REVIEW_TASK_TARGET and _migration_quizzes(con, day, tz) >= config.QUIZ_TASK_TARGET
    )
