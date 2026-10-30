import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import create_app


def test_family_share_switch_hides_other_member_numbers(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "family.sqlite3"))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.app_context():
        from auth import issue_token, password_hash
        from data.db import get_db
        con = get_db()
        con.execute("INSERT INTO users(username,password_hash,created_at) VALUES('Partner',?,'now')", (password_hash('partner'),))
        partner = con.execute("SELECT * FROM users WHERE username='Partner'").fetchone()
        token = issue_token(partner)
        con.execute("UPDATE users SET household_id=2 WHERE id=?", (partner['id'],))
        con.execute("INSERT INTO households(id,name,created_at) VALUES(2,'另家','now')")
        con.execute("INSERT INTO users(username,password_hash,role,created_at,household_id) VALUES('Peer','x','member','now',2)")
        peer_id = con.execute("SELECT id FROM users WHERE username='Peer'").fetchone()[0]
        con.commit()
    client = app.test_client()
    headers = {"Authorization": "Bearer " + token}
    response = client.get('/api/family', headers=headers)
    assert response.status_code == 200
    data = response.get_json()['data']
    my_id = data['me']['id']
    peer = next(x for x in data['members'] if x['id'] == peer_id)
    assert 'today_cards' in peer
    peer_token = None
    with app.app_context():
        from auth import issue_token
        from data.db import get_db
        peer_row = get_db().execute('SELECT * FROM users WHERE id=?', (peer_id,)).fetchone()
        peer_token = issue_token(peer_row)
    rr = client.post('/api/family/share', json={'shared': False}, headers={'Authorization': 'Bearer ' + peer_token})
    assert rr.status_code == 200
    response = client.get('/api/family', headers=headers)
    row = next(x for x in response.get_json()['data']['members'] if x['id'] == peer_id)
    assert row == {'id': peer['id'], 'username': peer['username'], 'shared': False}


def test_coverage_is_per_member_not_inherited(tmp_path, monkeypatch):
    """同一家庭里，别人的复习不能让我的覆盖率变高。"""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "coverage.sqlite3"))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.app_context():
        from auth import issue_token, password_hash
        from data.db import get_db
        con = get_db()
        con.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES('Owner',?,'owner','now')",
                    (password_hash('owner-pass'),))
        owner = con.execute("SELECT * FROM users WHERE username='Owner'").fetchone()
        con.execute("INSERT INTO subjects(name,slug,created_at) VALUES('demo','demo','now')")
        bid = con.execute("INSERT INTO books(subject_id,title,slug,created_at,owner_id) VALUES(1,'B','b','now',?)",
                          (owner['id'],)).lastrowid
        chid = con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,unlocked_at,status) VALUES(?,'c1',1,'a1','now','unlocked')", (bid,)).lastrowid
        cp = con.execute("INSERT INTO concepts(chapter_id,name,concept_uid) VALUES(?,'cp','cp1')", (chid,)).lastrowid
        for i in range(4):
            cid = con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,created_at)"
                              " VALUES(?,1,?,'x','s',?,'new','now')",
                              (cp, f'f{i}', f'h{i}')).lastrowid
            if i < 2:  # 只有 owner 学过
                con.execute("INSERT INTO card_reviews(card_id,user_id,result,learned_at) VALUES(?,?,'good',datetime('now'))",
                            (cid, owner['id']))
        con.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES('Clean',?,'member','now')",
                    (password_hash('clean-pass'),))
        clean = con.execute("SELECT * FROM users WHERE username='Clean'").fetchone()
        con.execute("UPDATE users SET household_id=(SELECT household_id FROM users WHERE id=?) WHERE id=?",
                    (owner['id'], clean['id']))
        con.commit()
        clean_token = issue_token(clean)
        owner_token = issue_token(owner)
    client = app.test_client()
    data = client.get('/api/family', headers={"Authorization": "Bearer " + owner_token}).get_json()['data']
    mine = next(x for x in data['members'] if x['id'] == owner['id'])
    other = next(x for x in data['members'] if x['id'] == clean['id'])
    assert mine['coverage'] == 50, mine      # 4 张里自己学过 2 张
    assert other['coverage'] == 0, other     # 新成员不得继承 50%
