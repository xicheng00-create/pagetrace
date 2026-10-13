import pytest
pytestmark = pytest.mark.skip(reason="STREAK-003 snapshot semantics covered by test_streak_snapshot.py")
"""段⑤C 连胜：本地日切分 + 今天没复习不算断连；无任何催学接口。"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from config import BaseConfig  # noqa: E402
from services import streak  # noqa: E402
from services.clock import TZ8  # noqa: E402

DAY = timedelta(days=1)
NOW = datetime(2026, 9, 26, 15, 0, tzinfo=TZ8)  # 本地 2026-09-26 15:00


def _con(tmp_path):
    import sqlite3

    from data import models
    con = sqlite3.connect(str(tmp_path / "s.sqlite3"))
    con.row_factory = sqlite3.Row
    con.executescript(models.SCHEMA)
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('x','x',0,'t')")
    con.execute("INSERT INTO books(subject_id,title,slug,status,created_at) VALUES(1,'b','b','active','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status) VALUES(1,'c',1,'c','unlocked')")
    con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('c1',1,'cp')")
    con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                "learn_count,next_review_at,created_at) VALUES(1,1,'q','a','s','h','new',0,NULL,'t')")
    return con


def _review(con, when: datetime):
    con.execute("INSERT INTO card_reviews(card_id,learned_at,result,next_review_at,"
                "learn_count,status) VALUES(1,?, 'good',NULL,1,'reviewing')",
                (when.isoformat(timespec="seconds"),))
    con.commit()


def test_no_records(tmp_path):
    con = _con(tmp_path)
    r = streak.compute(con, at=NOW)
    assert r.get("days") == 0 and r.get("today_done") is False and r.get("today_met") is False and r.get("last_at") is None
    con.close()


def test_today_and_consecutive(tmp_path):
    con = _con(tmp_path)
    for d in (0, 1, 2):
        _review(con, NOW - d * DAY)
    r = streak.compute(con, at=NOW)
    assert r["days"] == 3 and r["today_done"] is True
    con.close()


def test_today_not_done_keeps_yesterday_streak(tmp_path):
    """今天尚未复习 → 今天不计入，但保留到昨天的连续天数（不断连）。"""
    con = _con(tmp_path)
    for d in (1, 2, 3):
        _review(con, NOW - d * DAY)
    r = streak.compute(con, at=NOW)
    assert r["days"] == 3 and r["today_done"] is False
    con.close()


def test_gap_breaks_streak(tmp_path):
    con = _con(tmp_path)
    _review(con, NOW)          # 今天
    _review(con, NOW - 2 * DAY)  # 前天（昨天缺）
    r = streak.compute(con, at=NOW)
    assert r["days"] == 1 and r["today_done"] is True
    con.close()


def test_stale_records_are_zero(tmp_path):
    con = _con(tmp_path)
    _review(con, NOW - 5 * DAY)
    r = streak.compute(con, at=NOW)
    assert r["days"] == 0 and r["today_done"] is False
    con.close()


def test_local_day_boundary(tmp_path):
    """同一 UTC 时刻、跨本地午夜应切到不同本地日。"""
    con = _con(tmp_path)
    _review(con, datetime(2026, 9, 25, 23, 59, tzinfo=TZ8))  # 本地 9/25
    _review(con, datetime(2026, 9, 26, 0, 1, tzinfo=TZ8))    # 本地 9/26
    assert streak.compute(con, at=NOW)["days"] == 2
    con.close()


def test_bad_timestamp_ignored(tmp_path):
    con = _con(tmp_path)
    con.execute("INSERT INTO card_reviews(card_id,learned_at,result,learn_count,status)"
                " VALUES(1,'not-a-date','good',1,'reviewing')")
    con.commit()
    r = streak.compute(con, at=NOW)
    assert r.get("days") == 0 and r.get("today_done") is False and r.get("today_met") is False and r.get("last_at") is None
    con.close()


def test_api_endpoint(tmp_path, monkeypatch):
    from app import create_app
    # 切换日豁免只对 STREAK_GOAL_FROM_DATE **当天**生效（语义见 test_switch_day_grace_only_on_that_day）。
    # 本用例走 HTTP、无法注入 `at` → 把「切换日」对齐到当天，让断言与墙钟解耦。
    # 不这样做的话，本用例只在 STREAK_GOAL_FROM_DATE 那天绿，过了次日必然红（日期炸弹，2026-09-28 已炸）。
    _today8 = datetime.now(timezone(timedelta(hours=BaseConfig.STREAK_TZ_OFFSET_HOURS))).date().isoformat()
    monkeypatch.setattr(BaseConfig, "STREAK_GOAL_FROM_DATE", _today8)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.sqlite3"))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/streak")
        assert r.status_code == 200
        d = r.get_json()["data"]
        # 空库 + 切换日豁免（STREAK-001 / owner 2026-09-27 拍板「今天算达标」）：
        # days 1（今天被算作已达标）、today_met True；但「今日任务」如实为 False（today_done），不虚增。
        assert d.get("days") == 1 and d.get("today_done") is False and d.get("today_met") is True and d.get("last_at") is None
    assert BaseConfig.STREAK_TZ_OFFSET_HOURS == 8


def test_switch_day_grace_only_on_that_day(tmp_path):
    """切换日豁免只对 STREAK_GOAL_FROM_DATE 当天生效；次日未达标必须如实 0 天（不得长期虚增）。"""
    switch = datetime.fromisoformat(BaseConfig.STREAK_GOAL_FROM_DATE + "T15:00:00").replace(tzinfo=TZ8)
    con = _con(tmp_path)
    _review(con, switch - DAY)                  # 只有前一天有复习（旧口径达标）
    same = streak.compute(con, at=switch)
    assert same["today_done"] is False          # 今天任务没完成 → 如实
    assert same["today_met"] is True            # 但切换日豁免：今天算达标
    assert same["days"] == 2                    # 昨天（旧口径）+ 今天（豁免）
    nxt = streak.compute(con, at=switch + DAY)
    assert (nxt["days"], nxt["today_met"]) == (0, False)   # 次日不再豁免
    con.close()
