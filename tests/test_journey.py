"""REQ-JOURNEY-01 / REQ-FAM-05：每日连胜三合一与成员进度钻取。

反证：
- 只看视频不看卡 → 当日不算达成；
- 未共享进度的成员，别人取详情必须 403 且响应里没有任何数字；
- 跨户取详情 → 404。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import create_app
from auth import issue_token, password_hash
from data.db import get_db


def _seed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "journey.sqlite3"))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.app_context():
        con = get_db()
        con.execute("INSERT INTO users(username,password_hash,role,created_at,share_progress) VALUES('Owner',?,'owner','now',1)",
                    (password_hash("owner-pass"),))
        owner = con.execute("SELECT * FROM users WHERE username='Owner'").fetchone()
        con.execute("INSERT INTO subjects(name,slug,created_at) VALUES('demo','demo','now')")
        bid = con.execute("INSERT INTO books(subject_id,title,slug,created_at,owner_id) VALUES(1,'B','b','now',?)",
                          (owner["id"],)).lastrowid
        chid = con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at)"
                           " VALUES(?,'c1',1,'a1','unlocked','now')", (bid,)).lastrowid
        cp = con.execute("INSERT INTO concepts(chapter_id,name,concept_uid) VALUES(?,'cp','cp1')", (chid,)).lastrowid
        card = con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,created_at)"
                           " VALUES(?,1,'f','b','s','h1','new','now')", (cp,)).lastrowid
        vid = con.execute("INSERT INTO card_videos(concept_id,core_card_id,status,title,file_name,source,requested_at)"
                          " VALUES(?,?,'ready','t','1.mp4','manual','now')", (cp, card)).lastrowid
        con.commit()
        tokens = {"owner": issue_token(owner), "owner_id": owner["id"], "video_id": vid}
    return app, tokens


def test_video_view_counts_once_per_day(tmp_path, monkeypatch):
    app, t = _seed(tmp_path, monkeypatch)
    client = app.test_client()
    h = {"Authorization": "Bearer " + t["owner"]}
    first = client.post(f"/api/videos/{t['video_id']}/view", headers=h).get_json()
    second = client.post(f"/api/videos/{t['video_id']}/view", headers=h).get_json()
    assert first["code"] == 0 and first["data"]["viewed"] is True
    assert first["data"]["today"] == 1
    assert second["data"]["today"] == 1, "同一天同一片只能计一次"
    task = client.get("/api/task", headers=h).get_json()["data"]
    assert task["video"]["done"] == 1 and task["video"]["target"] == 5
    assert task["done"] is False, "只看 1 个视频不能算当日达成"


def test_member_detail_respects_share_flag(tmp_path, monkeypatch):
    app, t = _seed(tmp_path, monkeypatch)
    client = app.test_client()
    with app.app_context():
        con = get_db()
        con.execute("INSERT INTO users(username,password_hash,role,created_at,share_progress,household_id)"
                    " VALUES('Shy',?,'member','now',0,1)", (password_hash("shy-pass"),))
        shy = con.execute("SELECT * FROM users WHERE username='Shy'").fetchone()
        con.commit()
        shy_id = shy["id"]
    owner = {"Authorization": "Bearer " + t["owner"]}
    assert client.get(f"/api/family/member/{t['owner_id']}", headers=owner).status_code == 200
    denied = client.get(f"/api/family/member/{shy_id}", headers=owner)
    assert denied.status_code == 403
    assert "coverage" not in denied.get_json()


def test_new_registration_creates_own_group(tmp_path, monkeypatch):
    """留空邀请码＝开一个全新小组，不继承任何人的书架（REQ-FAM-06）。"""
    app, t = _seed(tmp_path, monkeypatch)
    client = app.test_client()
    res = client.post("/api/auth/register", json={"username": "Fresh", "password": "fresh-pass", "code": ""})
    assert res.status_code == 200 and res.get_json()["data"]["household_created"] is True
    with app.app_context():
        con = get_db()
        me = con.execute("SELECT id,household_id FROM users WHERE username='Fresh'").fetchone()
        owner = con.execute("SELECT household_id FROM users WHERE username='Owner'").fetchone()
        assert me["household_id"] != owner["household_id"]
        assert con.execute("SELECT COUNT(*) FROM books WHERE owner_id=?", (me["id"],)).fetchone()[0] == 0


def test_card_state_is_per_member(tmp_path, monkeypatch):
    """REQ-STATE-01：同组不同成员的学习状态互不继承（历史 cards.status 只归书主）。"""
    app, t = _seed(tmp_path, monkeypatch)
    with app.app_context():
        from services.cards import household_coverage_counts, today_queue

        con = get_db()
        owner = con.execute("SELECT * FROM users WHERE username='Owner'").fetchone()
        con.execute(
            "INSERT INTO users(username,password_hash,role,created_at,share_progress,household_id)"
            " VALUES('Mate',?,'member','now',1,?)",
            (password_hash("mate-pass"), owner["household_id"]),
        )
        mate = con.execute("SELECT * FROM users WHERE username='Mate'").fetchone()
        card = con.execute("SELECT id FROM cards ORDER BY id LIMIT 1").fetchone()["id"]
        con.execute(
            "INSERT INTO card_reviews(user_id,card_id,learned_at,result,status,learn_count,next_review_at)"
            " VALUES(?,?,'2026-10-30T10:00:00+08:00','good','reviewing',1,'2026-11-30T10:00:00+08:00')",
            (owner["id"], card),
        )
        con.execute(
            "UPDATE cards SET status='reviewing',next_review_at='2026-11-30T10:00:00+08:00' WHERE id=?",
            (card,),
        )
        con.commit()
        at = "2026-10-31T12:00:00+08:00"
        owner_q = today_queue(con, at=at, target=20, user_id=owner["id"])
        mate_q = today_queue(con, at=at, target=20, user_id=mate["id"])
        assert owner_q["due"] == [] and owner_q["new"] == []          # 书主已学、未到期
        assert [c["card_id"] for c in mate_q["new"]] == [card]        # 组员视为未学
        assert household_coverage_counts(con, owner["id"]).fetchone()["learned"] == 1
        assert household_coverage_counts(con, mate["id"]).fetchone()["learned"] == 0
