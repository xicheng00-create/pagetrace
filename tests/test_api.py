"""段④ API：钻取 / today 到期队列 / 三档复习 / progress。"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402
from config import BaseConfig  # noqa: E402

from scripts import ingest_kb  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cards-contract-1.jsonl"
# DATA-006：学科在 UI/接口里的显示名来自 config.SUBJECT_LABELS（契约只给 slug）
SUBJECT_LABEL = BaseConfig.SUBJECT_LABELS["psychology"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "api.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    ingest_kb.ingest_file(con, FIXTURE)
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _d(client, url):
    r = client.get(url)
    assert r.status_code == 200, url
    return r.get_json()["data"]


def test_subjects_metrics(client):
    d = _d(client, "/api/subjects")
    s = d["subjects"][0]
    assert s["slug"] == "psychology" and s["unlearned"] == 3
    assert s["mastered"] == 0 and s["due"] == 0
    # 0.4.1（DATA-005）：学科级只给汇总，不再有单一「解锁到第几章」
    assert "unlocked_upto" not in s
    assert s["books_total"] == 1 and s["chapters_total"] == 2 and s["cards_total"] == 3


def test_books_requires_subject(client):
    assert client.get("/api/books").status_code == 400
    books = _d(client, "/api/books?subject_id=1")["books"]
    assert books[0]["chapters_total"] == 2 and books[0]["chapters_unlocked"] == 1


def test_chapters_lock_reason(client):
    chs = _d(client, "/api/chapters?book_id=1")["chapters"]
    assert chs[0]["unlocked"] is True and chs[0]["lock_reason"] is None
    assert chs[1]["unlocked"] is False and "上一章未达标" in chs[1]["lock_reason"]
    assert client.get("/api/chapters").status_code == 400


def test_concepts_locked_and_unlocked(client):
    chs = _d(client, "/api/chapters?book_id=1")["chapters"]
    locked = _d(client, f"/api/concepts?chapter_id={chs[1]['id']}")
    assert locked["locked"] is True and locked["concepts"] == []
    open_ = _d(client, f"/api/concepts?chapter_id={chs[0]['id']}")
    assert open_["locked"] is False and len(open_["concepts"]) == 2
    assert client.get("/api/concepts").status_code == 400


def test_cards_list(client):
    cid = _d(client, "/api/concepts?chapter_id=1")["concepts"][0]["id"]
    cards = _d(client, f"/api/cards?concept_id={cid}")["cards"]
    assert len(cards) == 1 and cards[0]["status"] == "new"
    assert client.get("/api/cards").status_code == 400


def test_progress_four_numbers(client):
    s = _d(client, "/api/progress")["subjects"][0]
    for k in ("unlearned", "due", "mastered", "learned",
              "books_total", "chapters_total", "chapters_unlocked", "cards_total"):
        assert k in s
    assert "unlocked_upto" not in s  # DATA-005：学科级不得冒名单值


def test_today_due_queue_and_review(client):
    # 段⑤A：新卡也要进队列（否则空页面）——已解锁第 1 章有 2 张新卡
    d = _d(client, "/api/today")
    assert d["due"] == [] and len(d["new"]) == 2 and d["count"] == 2
    # DATA-006：队列里的 `subject` 是**显示名**（库内 subjects.name），不再是 slug。
    # 原断言写死 "psychology" = 把当时的显示名缺陷固化成了期望值，故随 0.5.1 一并纠正。
    assert d["new"][0]["status"] == "new" and d["new"][0]["subject"] == SUBJECT_LABEL
    # 造一张到期卡 → 到期优先
    with client.application.app_context():
        from data.db import get_db
        get_db().execute(
            "UPDATE cards SET status='learning', learn_count=1,"
            " next_review_at='2000-01-01T00:00:00+08:00' WHERE id=1")
        get_db().commit()
    d = _d(client, "/api/today")
    assert d["due"][0]["card_id"] == 1 and d["count"] == 2  # 1 到期 + 1 剩新卡
    assert d["count"] == len(d["due"]) + len(d["new"])


def test_review_submit_grades(client):
    with client.application.app_context():
        from data.db import get_db
        get_db().execute("UPDATE cards SET status='learning', learn_count=1,"
                         " next_review_at='2000-01-01T00:00:00+08:00' WHERE id=1")
        get_db().commit()
    r = client.post("/api/review/1", json={"result": "good"})
    assert r.status_code == 200
    assert r.get_json()["data"]["card"]["learn_count"] == 2
    assert client.post("/api/review/1", json={"result": "meh"}).status_code == 400
    assert client.post("/api/review/999", json={"result": "good"}).status_code == 404
    assert client.post("/api/review/1", json={}).status_code == 400
