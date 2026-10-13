"""RPT-001 本周概况：窗口（本周一 00:00 本地时区起）、复习卡数、作答/判对/正确率、最弱一章。

关键断言：
- 边界：周一 00:00 **前 1 分钟**的数据**不计入**；
- 正确率 = 判对 ÷ 已作答（QUIZ-005 同一函数）；**0 作答 → None（前端显 —，不显 0%）**；
- 最弱一章与 WEAK-001 同一聚合口径。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402

from scripts.ingest_store import connect  # noqa: E402
from services import report  # noqa: E402
from services.clock import TZ8, iso  # noqa: E402

AT = datetime(2026, 9, 27, 10, 0, tzinfo=TZ8)  # 周日
WEEK_START = report.week_start(AT)                                    # 2026-09-21 周一 00:00


def _seed(db):
    con = connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('心理学','psychology',0,'t')")
    con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,1,1,'书A','book-a','active','t')")
    con.execute("INSERT INTO chapters(id,book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,1,'第一章',1,'第一章','unlocked','t')")
    con.execute("INSERT INTO concepts(id,chapter_id,concept_uid,name) VALUES(1,1,'c1','概念1')")
    con.execute("INSERT INTO cards(id,concept_id,subject_id,front,back,source,content_hash,"
                "status,learn_count,created_at) VALUES(1,1,1,'卡1','答1','s','h1','reviewing',1,'t')")
    con.commit()
    return con


def _attempt(con, *, when_utc: str, is_correct: int, card_id: int = 1, tag: str = "t") -> None:
    item = con.execute(
        "INSERT INTO quiz_items(card_id,type,stem,options,answer_key,points,source,"
        "content_hash,created_at) VALUES(?,?,?,?,?,1,'fallback',?, 't')",
        (card_id, 'bool', f'题{tag}', '["对","错"]', "对", f"qh-{tag}")).lastrowid
    con.execute('INSERT INTO quiz_attempts(user_id,item_id,card_id,session_id,my_answer,is_correct,created_at) VALUES(1,?,1,?,?,?,?)', (item, f"s-{tag}", "对", is_correct, when_utc))


def _review(con, *, when: str) -> None:
    con.execute("INSERT INTO card_reviews(user_id,card_id,learned_at,result,next_review_at,learn_count,status) VALUES(1,1,?,'good',NULL,1,'reviewing')", (when,))


def test_week_start_is_monday_midnight_local():
    assert WEEK_START.weekday() == 0 and WEEK_START.hour == 0 and WEEK_START.minute == 0
    assert WEEK_START.tzinfo is not None


def test_window_boundary_excludes_one_minute_early(tmp_path):
    con = _seed(tmp_path / "win.sqlite3")
    before = WEEK_START - timedelta(minutes=1)
    # 复习：起点前 1 分钟 → 不计入；起点整 → 计入
    _review(con, when=iso(before))
    _review(con, when=iso(WEEK_START))
    # 作答：UTC 起点前 1 分钟 → 不计入；起点整 → 计入
    start_utc = WEEK_START.astimezone(timezone.utc)
    _attempt(con, when_utc=(start_utc - timedelta(minutes=1)).isoformat(timespec="seconds"),
             is_correct=0, tag="early")
    _attempt(con, when_utc=start_utc.isoformat(timespec="seconds"), is_correct=1, tag="on")
    con.commit()
    d = report.weekly_report(con, at=AT)
    assert d["reviewed_cards"] == 1, "周一 00:00 前 1 分钟的复习不得计入"
    assert d["quiz_answered"] == 1, "周一 00:00 前 1 分钟的作答不得计入"
    assert d["quiz_correct"] == 1
    con.close()


def test_accuracy_ratio_and_none_when_zero(tmp_path):
    con = _seed(tmp_path / "acc.sqlite3")
    d0 = report.weekly_report(con, at=AT)
    assert d0["quiz_answered"] == 0 and d0["accuracy"] is None   # 0 作答 → None（前端显 —）
    on = WEEK_START.astimezone(timezone.utc).isoformat(timespec="seconds")
    _attempt(con, when_utc=on, is_correct=1, tag="a")
    _attempt(con, when_utc=on, is_correct=0, tag="b")
    _attempt(con, when_utc=on, is_correct=0, tag="c")
    con.commit()
    d = report.weekly_report(con, at=AT)
    assert (d["quiz_answered"], d["quiz_correct"], d["accuracy"]) == (3, 1, 33)
    con.close()


def test_reviewed_cards_dedup(tmp_path):
    con = _seed(tmp_path / "dedup.sqlite3")
    for i in range(3):
        _review(con, when=iso(WEEK_START + timedelta(hours=i)))
    con.commit()
    assert report.weekly_report(con, at=AT)["reviewed_cards"] == 1   # 同一卡去重
    con.close()


def test_weakest_chapter_uses_week_window(tmp_path):
    con = _seed(tmp_path / "weak.sqlite3")
    on = WEEK_START.astimezone(timezone.utc).isoformat(timespec="seconds")
    early = (WEEK_START - timedelta(days=1)).astimezone(timezone.utc).isoformat(timespec="seconds")
    _attempt(con, when_utc=on, is_correct=0, tag="w1")
    _attempt(con, when_utc=on, is_correct=0, tag="w2")
    _attempt(con, when_utc=early, is_correct=0, tag="old")     # 上周 → 不计入最弱章
    con.commit()
    d = report.weekly_report(con, at=AT)
    assert d["weakest_chapter"]["chapter"] == "第一章"
    assert d["weakest_chapter"]["wrong_count"] == 2 and d["weakest_chapter"]["card_count"] == 1


def test_report_api_endpoint(tmp_path, monkeypatch):
    db = tmp_path / "api.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = _seed(db)
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/report")
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert set(d) == {"week_start", "reviewed_cards", "quiz_answered", "quiz_correct",
                          "accuracy", "weakest_chapter"}
        assert d["accuracy"] is None and d["weakest_chapter"] is None
