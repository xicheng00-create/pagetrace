"""今日任务与打卡（TASK-001 / GOAL-001，v0.6.0）。

任务构成（口径写死，🔒 对后续一律适用）：
- **今日复习 N 张**（GOAL-001）：N = `min(REVIEW_TASK_TARGET, 今日可复习总数)`，**不再**等于「当天到期数」。
  - 今日可复习总数 = `到期池 ∪ 未学新卡池`（**只计已解锁章**，与今日队列同口径）。
    到期池 = `|{当前仍到期} ∪ {今日已复习的卡}|` —— 复习会把到期卡推离到期集，
    并入「今日已复习」后目标在一天内稳定（复习一张、目标不减、完成数 +1），不会中途缩水。
  - 上限 30 是「每日目标」不是「硬配额」（无催学底色，SCHED-003）；新卡池消耗是接受的代价。
  - **退化态**：可复习总数为 0 → `target=0` 且响应带非空 `reason`（供 UI-003 置灰文案）。
- **出题 M 题**：M = 今日测验目标题数（`config.QUIZ_TASK_TARGET`，单点配置）。
- **完成判定**：复习已完成数 ≥ N **且** 测验已完成数 ≥ M → 当日 `done`；两子项各自算 `complete`。
- **连胜只读**：本模块不计算也不改写连胜（连胜仍由 `services/streak.py` 按「有复习记录的天数」定义）。
  本模块**不含任何催学文案/提醒阶梯**（OPS-004 / SCHED-003）。

「今天」按本地日切分（东八区，与连胜同口径）。`learned_at` 存东八区 ISO，`quiz_attempts.created_at`
存 UTC ISO —— 后者按 UTC 边界比较，避免字典序串时区。
"""

from __future__ import annotations

from datetime import UTC, datetime

from config import BaseConfig
from flask import g

from services import cards as card_pool
from services.clock import iso, now


def _uid(user_id=None):
    if user_id is not None:
        return user_id
    try:
        uid = getattr(g, "user_id", None)
    except RuntimeError:
        uid = None
    if uid is None:
        try:
            from flask import has_request_context
            if not has_request_context():
                return 1
        except RuntimeError:
            return 1
        raise RuntimeError("authenticated user required")
    return uid


_EMPTY_REASON = "新卡池已空，今日无卡可复习"


def _day_window(at: datetime) -> tuple[datetime, str]:
    start = at.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, iso(start)


def _quiz_done_today(con, day_start_utc_iso: str, user_id=None) -> int:
    user_id = user_id or _uid()
    """今日已作答题数（按题去重）。`created_at` 为 UTC ISO，故与 UTC 边界比。"""
    row = con.execute(
        "SELECT COUNT(DISTINCT item_id) AS n FROM quiz_attempts WHERE user_id=? AND created_at >= ?",
        (user_id, day_start_utc_iso),
    ).fetchone()
    return row["n"] or 0


def _video_done_today(con, day: str, user_id=None) -> int:
    """今日看过的视频数（去重；只要播放过即计一次，见 VIDEO-VIEW-001）。"""
    user_id = user_id or _uid()
    row = con.execute("SELECT COUNT(*) AS n FROM video_views WHERE user_id=? AND day=?", (user_id, day)).fetchone()
    return row["n"] or 0


def _available(con, at_iso: str, day_start_iso: str, book_ids: list[int] | None = None, user_id=None) -> int:
    """今日可复习总数仅统计当前用户已解锁章。"""
    user_id = user_id or _uid()
    due_pool = card_pool.available_due_count(con, at_iso, book_ids, day_start_iso, user_id).fetchone()[0]
    new_pool = card_pool.available_new_count(con, book_ids, user_id).fetchone()[0]
    return due_pool + new_pool


def today_task(
    con, at: datetime | None = None, quiz_target: int | None = None,
    book_ids: list[int] | None = None, user_id: int | None = None,
) -> dict:
    user_id = _uid(user_id)
    at = at or now()
    day_start, day_start_iso = _day_window(at)
    at_iso = iso(at)

    available = _available(con, at_iso, day_start_iso, book_ids, user_id)
    review_target = min(BaseConfig.REVIEW_TASK_TARGET, available)

    reviewed = (
        con.execute(
            "SELECT COUNT(DISTINCT card_id) AS n FROM card_reviews WHERE user_id=? AND learned_at >= ?",
            (user_id, day_start_iso),
        ).fetchone()["n"]
        or 0
    )

    target = BaseConfig.QUIZ_TASK_TARGET if quiz_target is None else int(quiz_target)
    day_start_utc = day_start.astimezone(UTC).isoformat(timespec="seconds")
    quiz_done = _quiz_done_today(con, day_start_utc, user_id)

    video_target = BaseConfig.VIDEO_TASK_TARGET
    video_done = _video_done_today(con, day_start.date().isoformat(), user_id)

    review_complete = reviewed >= review_target
    quiz_complete = quiz_done >= target
    video_complete = video_done >= video_target
    return {
        "review": {
            "target": review_target,
            "done": reviewed,
            "complete": review_complete,
            "reason": "" if review_target > 0 else _EMPTY_REASON,
        },
        "quiz": {"target": target, "done": quiz_done, "complete": quiz_complete},
        "video": {"target": video_target, "done": video_done, "complete": video_complete},
        "done": bool(review_complete and quiz_complete and video_complete),
    }
