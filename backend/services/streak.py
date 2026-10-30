"""STREAK-003：以每日任务快照为唯一依据计算连胜。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from config import BaseConfig
from flask import g

from services.clock import iso, now
from services.tasks import today_task


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


def _tz():
    return timezone(timedelta(hours=BaseConfig.STREAK_TZ_OFFSET_HOURS))


def _stamps(con, user_id=None) -> list[datetime]:
    user_id = user_id or _uid()
    rows = con.execute(
        "SELECT learned_at FROM card_reviews WHERE user_id=? AND learned_at IS NOT NULL", (user_id,)
    ).fetchall()
    out = []
    for row in rows:
        try:
            dt = datetime.fromisoformat(str(row["learned_at"]))
        except (ValueError, TypeError):
            continue
        out.append(dt if dt.tzinfo else dt.replace(tzinfo=_tz()))
    return out


def record_day(con, at: datetime | None = None) -> dict:
    """覆盖写入今天的任务快照；历史行永远不触碰。"""
    at = at or now()
    uid = _uid()
    task = today_task(con, at=at)
    day = at.astimezone(_tz()).date().isoformat()
    import sqlite3
    import time as _time
    for _try in range(6):          # WAL 下并发写会瞬时 SQLITE_BUSY：短退避重试，不让读接口 500
        try:
            con.execute(
                "INSERT INTO streak_days(user_id,day,target,review_done,quiz_done,video_done,video_target,met,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,day) DO UPDATE SET target=excluded.target, "
                "review_done=excluded.review_done, quiz_done=excluded.quiz_done, video_done=excluded.video_done, "
                "video_target=excluded.video_target, met=MAX(streak_days.met, excluded.met), "
                "updated_at=excluded.updated_at",
            (
                uid,
                day,
                task["review"]["target"],
                task["review"]["done"],
                task["quiz"]["done"],
                task["video"]["done"],
                task["video"]["target"],
                int(task["done"]),
                iso(at),
            ),
        )
            con.commit()
            break
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or _try == 5:
                raise
            try:
                con.rollback()
            except Exception:
                pass
            _time.sleep(0.05 * (_try + 1))
    return task


def _covered_days(con, before: date, user_id=None) -> set:
    user_id = user_id or _uid()
    """达标日 ∪ 已消耗冰冻日（`before` 之前）。连胜与里程碑都按这个集合判定。"""
    met = {
        datetime.fromisoformat(r["day"]).date()
        for r in con.execute(
            "SELECT day FROM streak_days WHERE user_id=? AND day<? AND met=1", (user_id, before.isoformat())
        )
    }
    frozen = {
        datetime.fromisoformat(r["day"]).date()
        for r in con.execute(
            "SELECT day FROM streak_freezes WHERE user_id=? AND day<?", (user_id, before.isoformat())
        )
    }
    return met | frozen


def _run_length(covered: set, end: date) -> int:
    """以 `end` 为终点向前数连续覆盖天数；`end` 未被覆盖则 0。"""
    n = 0
    d = end
    while d in covered:
        n += 1
        d -= timedelta(days=1)
    return n


def _milestones(con, before: date, user_id=None) -> tuple:
    user_id = user_id or _uid()
    """按「达标 ∪ 已冰冻」的连续段逐日走，返回 (里程碑次数, 最长连续段)。

    - 段内位置照常前进（冰冻日占位，对齐 AI 小组 `streak_after` 含冰冻日）；
    - 但**只有达标日**落在 5 的倍数位时才发一枚 —— 冰冻日本身不发（同 AI 小组只数 checkin）,
      否则「花冰冻 → 段变长 → 再发冰冻」会自发放贷。
    """
    met = {
        datetime.fromisoformat(r["day"]).date()
        for r in con.execute(
            "SELECT day FROM streak_days WHERE user_id=? AND day<? AND met=1", (user_id, before.isoformat())
        )
    }
    frozen = {
        datetime.fromisoformat(r["day"]).date()
        for r in con.execute(
            "SELECT day FROM streak_freezes WHERE user_id=? AND day<?", (user_id, before.isoformat())
        )
    }
    covered = met | frozen
    if not covered:
        return 0, 0
    grants = longest = run = 0
    d = min(covered)
    while d < before:
        if d in covered:
            run += 1
            if d in met and run % 5 == 0:
                grants += 1
            longest = max(longest, run)
        else:
            run = 0
        d += timedelta(days=1)
    return grants, longest


def freeze_status(con, at: datetime | None = None) -> dict:
    at = at or now()
    uid = _uid()
    today = at.astimezone(_tz()).date()
    grants, longest = _milestones(con, today, uid)
    used = con.execute("SELECT COUNT(*) FROM streak_freezes WHERE user_id=?", (uid,)).fetchone()[0]
    granted = BaseConfig.FREEZE_BASE + grants
    return {
        "granted": granted,
        "used": used,
        "available": max(0, granted - used),
        "longest_streak": longest,
        "recent": [
            dict(r)
            for r in con.execute(
                "SELECT day,streak_kept FROM streak_freezes WHERE user_id=? ORDER BY day DESC LIMIT 3", (uid,)
            ).fetchall()
        ],
    }


def settle_freezes(con, at: datetime | None = None) -> dict:
    """惰性结算**最后一段缺口**（`最后一次达标日+1 … 昨天`）：
    - 只补这一段：早先已经断掉的缺口不回溯消耗（历史断点不该花掉今天的冰冻）；
    - 缺口天数 > 余额 → 一行都不写（部分覆盖不算保住），连胜按原规则归零；
    - `streak_kept` 记**冻结前的连胜天数**（终点=最后一次达标日，按「达标 ∪ 已冰冻」连续段数）。
    """
    at = at or now()
    uid = _uid()
    today = at.astimezone(_tz()).date()
    status = freeze_status(con, at)
    days = con.execute(
        "SELECT day,met FROM streak_days WHERE user_id=? AND day<? ORDER BY day", (uid, today.isoformat())
    ).fetchall()
    if not days:
        return status
    met_dates = [datetime.fromisoformat(r["day"]).date() for r in days if r["met"]]
    last_met = max(met_dates, default=None)
    if last_met is None:
        return status
    frozen_days = {
        datetime.fromisoformat(r["day"]).date()
        for r in con.execute("SELECT day FROM streak_freezes WHERE user_id=?", (uid,))
    }
    missing = []
    d = last_met + timedelta(days=1)
    while d < today:
        if d not in frozen_days and not any(r["day"] == d.isoformat() and r["met"] for r in days):
            missing.append(d)
        d += timedelta(days=1)
    if missing and status["available"] >= len(missing):
        kept = _run_length(_covered_days(con, last_met + timedelta(days=1), uid), last_met)
        for d in missing:
            con.execute(
                "INSERT OR IGNORE INTO streak_freezes(user_id,day,streak_kept,created_at) VALUES(?,?,?,?)",
                (uid, d.isoformat(), kept, iso(at)),
            )
    con.commit()
    return freeze_status(con, at)


def compute(con, at: datetime | None = None) -> dict:
    at = at or now()
    uid = _uid()
    today = at.astimezone(_tz()).date()
    task = record_day(con, at=at)
    freezes = settle_freezes(con, at)
    # Legacy snapshots are populated by migrate(); current-day writes never replay history.
    today_row = con.execute(
        "SELECT * FROM streak_days WHERE user_id=? AND day=?", (uid, today.isoformat())
    ).fetchone()
    today_snapshot_met = bool(today_row["met"])
    today_met = bool(task["done"])
    cursor = today if today_snapshot_met else today - timedelta(days=1)
    days = 0
    while True:
        row = con.execute(
            "SELECT met FROM streak_days WHERE user_id=? AND day=?", (uid, cursor.isoformat())
        ).fetchone()
        frozen = con.execute(
            "SELECT 1 FROM streak_freezes WHERE user_id=? AND day=?", (uid, cursor.isoformat())
        ).fetchone()
        if not frozen and (row is None or not row["met"]):
            break
        days += 1
        cursor -= timedelta(days=1)
    stamps = _stamps(con, uid)
    return {
        "days": days,
        "today_done": bool(task["done"]),
        "today_met": today_met,
        "freezes": freezes,
        "last_at": iso(max(stamps)) if stamps else None,
    }
