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
