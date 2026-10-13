"""薄弱点聚合（WEAK-001）+ 本周概况（RPT-001）—— **只读统计**，前端零计算。

口径（🔒 对后续一律适用）：
- **薄弱点按章聚合**（与错题本按卡不同）：数据源 = `quiz_attempts(is_correct=0)` → 卡 → 章；
  每章给出 `wrong_count`（错次总数）与 `card_count`（涉及卡数），**按错次降序**；**只出现有错题的章**。
- **本周窗口** = **本周一 00:00（本地时区 = 东八区）起**；`card_reviews.learned_at` 是本地 ISO，
  直接与窗口起点比较；`quiz_attempts.created_at` 是 **UTC** ISO，故窗口起点先转 UTC 再比较。
- 正确率 = `判对 ÷ 已作答`（与 QUIZ-005 **同一分子分母口径、同一函数** `quiz.score_pct`）；
  作答数为 0 → `accuracy = None`（前端显示 `—`，**不得显示 0%**）。
- 最弱一章 = 与 WEAK-001 **同一聚合**（本文件 `weak_chapters`），窗口内取错次最多者。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask import g

from services import cards as card_pool
from services import labels, quiz
from services.clock import iso, now


def _uid():
    uid = getattr(g, "user_id", None)
    if uid is None:
        raise RuntimeError("authenticated user required")
    return uid


def week_start(at: datetime | None = None) -> datetime:
    """本周一 00:00（本地时区），带时区。"""
    at = at or now()
    monday = (at - timedelta(days=at.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday


def _window_utc_iso(start: datetime) -> str:
    return start.astimezone(UTC).isoformat(timespec="seconds")


def weak_chapters(con, since_utc: str | None = None, user_id=None) -> list[dict]:
    """按章聚合错题（WEAK-001）：**只含有错题的章**、**按错次降序**；章内含涉及卡与错次。

    `since_utc`（UTC ISO，可选）限定统计窗口（RPT-001 用本周窗口；WEAK-001 用全量）。
    """
    user_id = user_id or _uid()
    rows = card_pool.weak_chapter_card_rows(con, since_utc, user_id).fetchall()

    buckets: dict[int, dict] = {}
    for r in rows:
        g = buckets.get(r["chapter_id"])
        if g is None:
            g = {
                "chapter_id": r["chapter_id"],
                "chapter": r["chapter"],
                "book": r["book"],
                "chapter_label": labels.display_fields({"chapter": r["chapter"]})["source_label"],
                "book_label": labels.display_fields({"book": r["book"]})["source_label"],
                "subject": r["subject"],
                "wrong_count": 0,
                "card_count": 0,
                "cards": [],
            }
            buckets[r["chapter_id"]] = g
        g["cards"].append(
            {
                **labels.display_fields({**dict(r), **(quiz.quizgen.card_context(con, r["card_id"], user_id) or {})}),
                "card_id": r["card_id"],
                "front": r["front"],
                "wrong_count": r["wrong_count"],
            }
        )
        g["wrong_count"] += r["wrong_count"]
    out = list(buckets.values())
    for g in out:
        g["card_count"] = len(g["cards"])
    # 按错次降序；并列时章 id 升序（稳定）
    out.sort(key=lambda g: (-g["wrong_count"], g["chapter_id"]))
    return out


def weekly_report(con, at: datetime | None = None) -> dict:
    """本周概况（RPT-001）：复习卡数 / 作答数 / 判对数 / 正确率 / 最弱一章。"""
    user_id = _uid()
    at = at or now()
    start = week_start(at)
    start_local_iso = iso(start)
    start_utc_iso = _window_utc_iso(start)

    reviewed = (
        con.execute(
            "SELECT COUNT(DISTINCT card_id) AS n FROM card_reviews WHERE user_id = ? AND learned_at >= ?",
            (user_id, start_local_iso),
        ).fetchone()["n"]
        or 0
    )
    row = con.execute(
        "SELECT COUNT(*) AS answered, SUM(is_correct) AS correct FROM quiz_attempts"
        " WHERE user_id = ? AND created_at >= ?",
        (user_id, start_utc_iso),
    ).fetchone()
    answered = row["answered"] or 0
    correct = row["correct"] or 0
    # 正确率 = 判对 ÷ 已作答（QUIZ-005 同一函数）；0 作答 → None（前端显 —，不显 0%）
    accuracy = quiz.score_pct(correct, answered) if answered else None

    weak = weak_chapters(con, since_utc=start_utc_iso, user_id=user_id)
    weakest = None
    if weak:
        w = weak[0]
        weakest = {
            "chapter_id": w["chapter_id"],
            "chapter": w["chapter"],
            "book": w["book"],
            "subject": w["subject"],
            "wrong_count": w["wrong_count"],
            "card_count": w["card_count"],
            "book_label": w["book_label"],
            "chapter_label": w["chapter_label"],
        }
    return {
        "week_start": start_local_iso,
        "reviewed_cards": reviewed,
        "quiz_answered": answered,
        "quiz_correct": correct,
        "accuracy": accuracy,
        "weakest_chapter": weakest,
    }
