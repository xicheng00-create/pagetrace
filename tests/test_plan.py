"""PLAN-001 复习计划视图：状态非 new 的卡、已到期在前 → 下次复习升序 + 间隔机械换算。

反向断言：
- 间隔文案必须由 `next_review_at` 机械换算（后端单点 `plan.when_label`）；
- 前端不得另算一套（见 `tests/test_frontend.py::test_plan_page_hooks`）。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402

from scripts.ingest_store import connect  # noqa: E402
from services import plan  # noqa: E402
from services.clock import TZ8, iso  # noqa: E402

AT = datetime(2026, 9, 27, 10, 0, tzinfo=TZ8)


def _seed(db, cards):
    """1 学科 / 1 书 / 1 章 / 1 概念；cards = [(front, status, next_review_at)]。"""
    con = connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('心理学','psychology',0,'t')")
    con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,1,1,'书A','book-a','active','t')")
    con.execute("INSERT INTO chapters(id,book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,1,'第1章',1,'第1章','unlocked','t')")
    con.execute("INSERT INTO concepts(id,chapter_id,concept_uid,name) VALUES(1,1,'c1','概念1')")
    for i, (front, status, nxt) in enumerate(cards, start=1):
        con.execute(
            "INSERT INTO cards(id,concept_id,subject_id,front,back,source,content_hash,status,"
            "learn_count,next_review_at,created_at) VALUES(?,1,1,?,?,'s',?,?,1,?,'t')",
            (i, front, f"答{i}", f"h{i}", status, nxt))
    con.commit()
    return con


# —— 间隔换算（机械、可证伪） ——
def test_when_label_mechanical_conversion():
    assert plan.when_label(iso(AT + timedelta(days=3)), AT) == "3 天后"
    assert plan.when_label(iso(AT - timedelta(hours=1)), AT) == "已到期"
    assert plan.when_label(iso(AT), AT) == "已到期"                 # 恰好到点 → 已到期
    assert plan.when_label(iso(AT + timedelta(hours=5)), AT) == "5 小时后"
    assert plan.when_label(iso(AT + timedelta(minutes=30)), AT) == "30 分钟后"
    assert plan.when_label(None, AT) == ""                          # 空值 → 空串（不抛）
    assert plan.when_label("不是时间", AT) == ""                     # 非法值 → 空串（不抛）


def test_when_label_day_boundary_not_hours():
    """跨过 24 小时必须走「N 天后」，不得报成 24 小时。"""
    assert plan.when_label(iso(AT + timedelta(hours=24)), AT) == "1 天后"


def test_when_label_naive_datetime_treated_as_local():
    """无时区的 ISO 一律按本地时区解读（防御式，不抛异常）。"""
    assert plan.when_label("2026-09-30T10:00:00", AT) == "3 天后"


# —— 排序 / 过滤 ——
def test_plan_items_due_first_then_ascending(tmp_path):
    db = tmp_path / "plan.sqlite3"
    con = _seed(db, [
        ("新卡", "new", None),                                  # 必须排除（status=new）
        ("三天后", "reviewing", iso(AT + timedelta(days=3))),
        ("已到期", "reviewing", iso(AT - timedelta(hours=1))),
        ("一天后", "learning", iso(AT + timedelta(days=1))),
    ])
    items = plan.plan_items(con, at=AT)
    assert [x["front"] for x in items] == ["已到期", "一天后", "三天后"]
    assert [x["when_label"] for x in items] == ["已到期", "1 天后", "3 天后"]
    assert [x["due"] for x in items] == [True, False, False]
    assert all(x["book"] == "书A" and x["chapter"] == "第1章" for x in items)
    assert "新卡" not in [x["front"] for x in items]
    con.close()


def test_plan_null_next_review_last(tmp_path):
    con = _seed(tmp_path / "p.sqlite3", [
        ("无时间", "reviewing", None),
        ("一天后", "reviewing", iso(AT + timedelta(days=1))),
        ("已到期", "reviewing", iso(AT - timedelta(minutes=5))),
    ])
    items = plan.plan_items(con, at=AT)
    assert [x["front"] for x in items] == ["已到期", "一天后", "无时间"]
    assert items[-1]["due"] is False and items[-1]["when_label"] == ""
    con.close()


def test_plan_api_endpoint(tmp_path, monkeypatch):
    db = tmp_path / "api.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = _seed(db, [("到期卡", "reviewing", "2020-01-01T00:00:00+08:00")])
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/plan")
        assert r.status_code == 200
        items = r.get_json()["data"]["items"]
        assert len(items) == 1
        it = items[0]
        assert set(it) == {"card_id", "front", "status", "status_label", "book", "chapter",
                           "concept", "title", "subtitle", "next_review_at", "due", "when_label", "source_label"}
        assert it["status_label"] == "复习中"  # MAST-003：后端下发 label（review → 复习中）
        assert it["due"] is True and it["when_label"] == "已到期"


def test_plan_empty_when_all_new(tmp_path):
    con = _seed(tmp_path / "e.sqlite3", [("新卡", "new", None)])
    assert plan.plan_items(con, at=AT) == []
    con.close()
