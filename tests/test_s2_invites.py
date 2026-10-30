"""Invitation validation, rollback, expiry, concurrency and registered-user isolation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app import create_app
from auth import SENTINEL_PASSWORD_HASH, issue_token, password_hash
from data.db import get_db
from services import clock


@pytest.fixture
def invite_app(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'invites.sqlite3'))
    app = create_app('development')
    app.config.update(TESTING=True)
    return app


def setup_owner(app):
    c = app.test_client()
    assert c.post('/api/auth/bootstrap', json={'username':'owner', 'password':'test-owner-password'}).status_code == 200
    assert c.post('/api/auth/login', json={'username':'owner', 'password':'test-owner-password'}).status_code == 200
    return c


def register(c, code, username='new-member', password='test-member-password'):
    return c.post('/api/auth/register', json={'code':code, 'username':username, 'password':password})


def test_state_only_boolean_and_claim(invite_app):
    c = invite_app.test_client()
    assert c.get('/api/auth/state').json['data'] == {'needs_bootstrap':True,'needs_claim':False}
    with invite_app.app_context():
        con = get_db()
        con.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES('owner',?,'owner','t')", (SENTINEL_PASSWORD_HASH,))
        con.commit()
    assert c.get('/api/auth/state').json['data'] == {'needs_bootstrap':False,'needs_claim':True}
    assert c.post('/api/auth/login', json={'username':'owner','password':'claim-password'}).status_code == 200
    assert c.get('/api/auth/state').json['data'] == {'needs_bootstrap':False,'needs_claim':False}


def test_invites_invalid_conflict_expiry_and_one_time(invite_app):
    owner = setup_owner(invite_app)
    outsider = invite_app.test_client()
    assert outsider.post('/api/invites').status_code == 401
    assert outsider.get('/api/invites').status_code == 401
    # 留空邀请码 → 新建自己的小组（独立客户端，避免占用 outsider）
    fresh = invite_app.test_client()
    assert fresh.post('/api/auth/register', json={'username': 'fresh-member', 'password': 'fresh-pass', 'code': ''}).status_code == 200
    assert register(outsider, 'bad-code').status_code == 401
    assert register(outsider, 'x'*257).status_code == 401
    assert register(outsider, 'bad', password='short').status_code == 400
    assert register(outsider, 'bad', username='').status_code == 400
    assert register(outsider, 'bad', username='x'*81).status_code == 400
    assert owner.get('/api/invites').json['data']['invites'] == []
    data = owner.post('/api/invites').json['data']
    code = data['code']
    assert 23.99 <= (clock.datetime.fromisoformat(data['expires_at']) - clock.now()).total_seconds()/3600 <= 24
    with invite_app.app_context():
        row = get_db().execute('SELECT * FROM invites').fetchone()
        assert code not in row['code_hash'] and row['code_hash'].startswith('pbkdf2_sha256$')
    assert register(outsider, code, 'owner').status_code == 409
    success = register(outsider, code)
    assert success.status_code == 200 and success.json['data']['role'] == 'member'
    assert 'HttpOnly' in success.headers['Set-Cookie']
    assert outsider.get('/api/auth/me').json['data']['username'] == 'new-member'
    assert outsider.post('/api/invites').status_code == 403
    assert outsider.get('/api/invites').status_code == 403
    assert register(invite_app.test_client(), code, 'second').status_code == 410
    listing = owner.get('/api/invites').json['data']['invites']
    assert listing[0]['status'] == '已用' and listing[0]['used_by']
    assert code not in str(listing) and 'code_hash' not in str(listing)
    expiring = owner.post('/api/invites').json['data']['code']
    with invite_app.app_context():
        con = get_db(); con.execute('UPDATE invites SET expires_at=? WHERE used_at IS NULL', ((clock.now()-timedelta(hours=1)).isoformat(),)); con.commit()
    assert '過期' in register(invite_app.test_client(), expiring).json['msg']
    assert owner.get('/api/invites').json['data']['invites'][0]['status'] == '過期'
    assert all(type(v) is bool for v in outsider.get('/api/auth/state').json['data'].values())


def test_concurrent_invite_claim_once(invite_app):
    owner = setup_owner(invite_app)
    code = owner.post('/api/invites').json['data']['code']
    def claim(i):
        return register(invite_app.test_client(), code, f'parallel-{i}').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, (1,2))) == [200,410]
    with invite_app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM users WHERE role='member'").fetchone()[0] == 1


def test_invited_member_shares_household_and_other_household_is_denied(invite_app):
    """REQ-FAM-04：同户成员共享书/章；跨户一律 403/404 且响应体不得出现书标题。"""
    owner = setup_owner(invite_app)
    with invite_app.app_context():
        con = get_db()
        con.execute("INSERT INTO subjects(name,slug,created_at) VALUES('demo','demo','t')")
        bid = con.execute("INSERT INTO books(subject_id,title,slug,created_at,owner_id) VALUES(1,'OWNER-PRIVATE-MARKER','private','t',1)").lastrowid
        con.commit()
    code = owner.post('/api/invites').json['data']['code']
    member = invite_app.test_client()
    assert register(member, code).status_code == 200
    # 同户：书架与章都能读到（家庭共享）
    shelf = member.get('/api/books?subject_id=1')
    assert shelf.status_code == 200 and [b['title'] for b in shelf.json['data']['books']] == ['OWNER-PRIVATE-MARKER']
    shared = member.get(f'/api/chapters?book_id={bid}')
    assert shared.status_code == 200
    # 跨户：搬去另一个 household 后必须拒绝，且不泄露标题
    with invite_app.app_context():
        con = get_db()
        other_hid = con.execute("INSERT INTO households(name,created_at) VALUES('别家','t')").lastrowid
        con.execute("UPDATE users SET household_id=? WHERE username<>'owner'", (other_hid,))
        con.commit()
    denied = member.get(f'/api/chapters?book_id={bid}')
    assert denied.status_code in (403, 404)
    assert 'OWNER-PRIVATE-MARKER' not in denied.get_data(as_text=True)
    own = member.get('/api/books?subject_id=1')
    assert own.status_code == 200 and own.json['data']['books'] == []
    print('G2 REGISTER PASS: 同户共享可见 / 跨户 403-404 且无 owner marker')


def test_owner_listing_scoped_to_creator(invite_app):
    owner = setup_owner(invite_app)
    with invite_app.app_context():
        con = get_db()
        uid = con.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES('owner2',?,'owner','t')", (password_hash('test-password'),)).lastrowid
        con.commit()
        token = issue_token({'id':uid,'username':'owner2','role':'owner'})
    second = invite_app.test_client()
    assert second.post('/api/invites', headers={'Authorization':'Bearer '+token}).status_code == 200
    assert owner.get('/api/invites').json['data']['invites'] == []
