"""WEAK-001 薄弱点页：**按章聚合**（与错题本按卡不同）、**只含有错题的章**、**按错次降序**。

数据源 = `quiz_attempts(is_correct=0)` → 卡 → 章；章内给出涉及卡与各自错次。
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402

from scripts.ingest_store import connect  # noqa: E402
from services import report  # noqa: E402


def _seed(db):
    """2 书 × 2 章：章 A（卡 A1/A2，错 3/1）、章 B（卡 B1，错 2）、章 C（无错题）。"""
    con = connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('心理学','psychology',0,'t')")
    con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,1,1,'书A','book-a','active','t')")
    con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,2,1,'书B','book-b','active','t')")
    chs = {1: (1, '第一章'), 2: (1, '第二章'), 3: (2, '第一章')}
    for cid, (bid, name) in chs.items():
        con.execute("INSERT INTO chapters(id,book_id,name,order_no,anchor,status,unlocked_at)"
                    " VALUES(?,?,?,?,?, 'unlocked','t')", (cid, bid, name, cid, name))
    cards = {1: (1, '卡A1'), 2: (1, '卡A2'), 3: (2, '卡B1'), 4: (3, '卡C1')}
    for card_id, (ch_id, front) in cards.items():
        con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES(?,?,?)",
                    (f"cp{card_id}", ch_id, f"概念{card_id}"))
        cpt = con.execute("SELECT id FROM concepts WHERE concept_uid=?", (f"cp{card_id}",)).fetchone()[0]
        con.execute("INSERT INTO cards(id,concept_id,subject_id,front,back,source,content_hash,"
                    "status,learn_count,created_at) VALUES(?,?,1,?,?,'s',?,'reviewing',1,'t')",
                    (card_id, cpt, front, f"答{card_id}", f"h{card_id}"))
    # 错题记录：(card_id, 错次)
    for card_id, n in ((1, 3), (2, 1), (3, 2)):
        for _ in range(n):
            item = con.execute(
                "INSERT INTO quiz_items(card_id,type,stem,options,answer_key,points,source,"
                "content_hash,created_at) VALUES(?,?,?,?,?,1,'fallback',?,'t')",
                (card_id, 'bool', f"题{card_id}", '["对","错"]', "对",
                 f"qh-{card_id}-{_}")).lastrowid
            con.execute("INSERT INTO quiz_attempts(user_id,item_id,card_id,session_id,my_answer,is_correct,created_at) VALUES(1,?,?,?,?,0,'2026-09-27T02:00:00+00:00')",
                        (item, card_id, f"s{card_id}-{_}", "对"))
    con.commit()
    return con


def test_weak_chapters_only_with_wrongs_sorted_desc(tmp_path):
    con = _seed(tmp_path / "weak.sqlite3")
    groups = report.weak_chapters(con)
    # 只出现有错题的章（章 C 无错题 → 不出现）；按错次降序：A(4) → B(2)
    assert [g["chapter"] for g in groups] == ["第一章", "第二章"]
    assert [g["wrong_count"] for g in groups] == [4, 2]
    assert [g["card_count"] for g in groups] == [2, 1]
    a = groups[0]
    assert a["book"] == "书A" and a["subject"] == "心理学"
    # 章内涉及卡按错次降序
    assert [c["front"] for c in a["cards"]] == ["卡A1", "卡A2"]
    assert [c["wrong_count"] for c in a["cards"]] == [3, 1]
    con.close()


def test_weak_empty(tmp_path):
    con = connect(str(tmp_path / "empty.sqlite3"))
    assert report.weak_chapters(con) == []
    con.close()


def test_weak_api_endpoint(tmp_path, monkeypatch):
    db = tmp_path / "api.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = _seed(db)
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/weak")
        assert r.status_code == 200
        chs = r.get_json()["data"]["chapters"]
        assert [g["wrong_count"] for g in chs] == [4, 2]
        assert all(g["cards"] for g in chs)
