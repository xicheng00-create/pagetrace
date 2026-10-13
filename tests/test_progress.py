"""0.4.1（DATA-004/005、UI-005）：学科级汇总、书级逐书取值。

反向断言：
- 学科级**不得**返回单一 unlocked_upto（跨书聚合冒名单值）。
- 两本进度不同的书，书层各自取值、互不污染。
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402
from services import progress  # noqa: E402

from scripts import ingest_kb  # noqa: E402


def _seed_two_books(db_path):
    """1 学科 / 2 书（各 3 章）/ 2 概念 / 7 张卡；两书各只解锁第 1 章。"""
    con = ingest_kb.connect(str(db_path))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('合成示例书12','demo',0,'t')")
    for bid, title, n in ((1, "书A", 4), (2, "书B", 3)):
        con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,?,1,?,?,'active','t')", (bid, title, title))
        for k in range(1, 4):
            con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at)"
                        " VALUES(?,?,?,?,?,?)",
                        (bid, f"第{k}章", k, f"第{k}章", "unlocked" if k == 1 else "locked",
                         "t" if k == 1 else None))
        ch1 = con.execute("SELECT id FROM chapters WHERE book_id=? AND order_no=1", (bid,)).fetchone()[0]
        cid = con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES(?,?,?)",
                          (f"c{bid}", ch1, f"概念{bid}")).lastrowid
        for i in range(n):
            con.execute(
                "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                "learn_count,next_review_at,created_at) VALUES(?,1,?,?,'s',?,'new',0,NULL,'t')",
                (cid, f"b{bid}q{i}", f"b{bid}a{i}", f"b{bid}h{i}"))
    con.commit()
    return con


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "prog.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = _seed_two_books(db)
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_subject_level_is_aggregate_and_has_no_single_chapter(tmp_path):
    """反向断言：学科级不返回单一 unlocked_upto，只给汇总。"""
    con = _seed_two_books(tmp_path / "p.sqlite3")
    s = progress.subject_metrics(con)[0]
    assert "unlocked_upto" not in s, "学科级不得出现单一「解锁到第几章」"
    assert s["books_total"] == 2 and s["chapters_total"] == 6  # 2 书 × 3 章
    assert s["chapters_unlocked"] == 2                          # 两书各解锁首章
    assert s["cards_total"] == 7 and s["unlearned"] == 7
    assert s["learned"] == 0 and s["mastered"] == 0 and s["due"] == 0
    con.close()


def test_book_level_progress_differs_per_book(client):
    """书层按该书自身章节取值：两书进度不同 → 两书显示不同。"""
    books = {b["title"]: b for b in
             client.get("/api/books?subject_id=1").get_json()["data"]["books"]}
    assert books["书A"]["chapters_total"] == 3 and books["书A"]["unlocked_upto"] == 1
    assert books["书B"]["chapters_total"] == 3 and books["书B"]["unlocked_upto"] == 1
    # 把书 A 推到已解锁第 2 章 → 两书数字必须分叉（书 B 不动）
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        ch2 = con.execute("SELECT id FROM chapters WHERE book_id=1 AND order_no=2").fetchone()[0]
        con.execute("UPDATE chapters SET unlocked_at='t' WHERE id=?", (ch2,))
        con.commit()
    books = {b["title"]: b for b in
             client.get("/api/books?subject_id=1").get_json()["data"]["books"]}
    assert books["书A"]["unlocked_upto"] == 2
    assert books["书B"]["unlocked_upto"] == 1  # 未被书 A 污染
    # 学科级仍是汇总，不冒名单值
    s = client.get("/api/progress").get_json()["data"]["subjects"][0]
    assert "unlocked_upto" not in s and s["chapters_unlocked"] == 3


def test_subject_payload_keys(client):
    s = client.get("/api/subjects").get_json()["data"]["subjects"][0]
    for k in ("books_total", "chapters_total", "chapters_unlocked", "cards_total",
              "unlearned", "due", "mastered", "learned", "mastery"):
        assert k in s, k
    assert "unlocked_upto" not in s


def _seed_five_cards_four_mastered(db_path):
    """1 学科 / 1 书 / 1 章 / 1 概念 / 5 卡（4 mastered + 1 review）。"""
    con = ingest_kb.connect(str(db_path))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('合成示例书12','demo',0,'t')")
    con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,1,1,'书A','book-a','active','t')")
    con.execute("INSERT INTO chapters(id,book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,1,'第1章',1,'第1章','unlocked','t')")
    cid = con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('c1',1,'概念1')").lastrowid
    for i in range(5):
        st = 'mastered' if i < 4 else 'reviewing'
        con.execute(
            "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
            "learn_count,next_review_at,created_at) VALUES(?,1,?,?,'s',?,?,1,'2020-01-01T00:00:00+08:00','t')",
            (cid, f"q{i}", f"a{i}", f"h{i}", st))
    con.execute(
        "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
        "learn_count,next_review_at,created_at) VALUES(?,1,'新卡','新答','s','newh','new',0,NULL,'t')",
        (cid,))
    con.commit()
    con.close()


def test_four_levels_mastery_ratios(tmp_path, monkeypatch):
    db = tmp_path / "mast.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    _seed_five_cards_four_mastered(db)
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        mastery = c.get("/api/subjects").get_json()["data"]["subjects"][0]["mastery"]
        assert {k: mastery[k] for k in ("m", "learned", "cards_total", "coverage", "evidence_cards", "state", "state_label")} == {"m": 94, "learned": 5, "cards_total": 6, "coverage": 83, "evidence_cards": 0, "state": "progress", "state_label": "进行中"}
        assert "num" not in mastery
        with app.app_context():
            con = ingest_kb.connect(str(db))
            for card in con.execute("SELECT id FROM cards LIMIT 2").fetchall():
                con.execute("INSERT INTO card_reviews(user_id,card_id,result,learned_at,status) VALUES(1,?,'good','2026-09-27T00:00:00+08:00','mastered')", (card[0],))
            con.commit(); con.close()
        mastery = c.get("/api/subjects").get_json()["data"]["subjects"][0]["mastery"]
        assert mastery["evidence_cards"] == 2 and mastery["state"] == "master"


def test_chapter_mastery_zero_denominator_not_started(tmp_path, monkeypatch):
    """新章 0 张已学 → mastery 分母 0，pct 0 且 started false（不除零）。"""
    db = tmp_path / "mast0.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('合成示例书12','demo',0,'t')")
    con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,1,1,'书A','book-a','active','t')")
    con.execute("INSERT INTO chapters(id,book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,1,'第1章',1,'第1章','unlocked','t')")
    con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('c1',1,'概念1')")
    con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                "learn_count,next_review_at,created_at) VALUES(1,1,'q','a','s','h','new',0,NULL,'t')")
    con.commit()
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        ch = c.get("/api/chapters?book_id=1").get_json()["data"]["chapters"][0]
        assert ch["mastery"] == {"m": None, "learned": 0, "cards_total": 1, "coverage": 0, "evidence_cards": 0, "state": "na", "state_label": "未评估"}
        b = c.get("/api/books?subject_id=1").get_json()["data"]["books"][0]
        assert b["mastery"]["m"] is None
