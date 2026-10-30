"""S2 认证真实 HTTP 回归；全部数据库均由 tmp_path 隔离。"""
import base64
import hashlib
import hmac
import json
import time

import pytest
from app import create_app
from auth import decode_token, issue_token, password_hash, verify_password
from data.db import get_db


@pytest.fixture
def auth_app(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'auth.sqlite3'))
    return create_app('development')


def signed(app, claims, algorithm='HS256'):
    def enc(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    message = enc({'alg': algorithm, 'typ': 'JWT'}) + '.' + enc(claims)
    secret = app.config.get('JWT_SECRET') or app.config.get('APP_SECRET')
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()).decode().rstrip('=')
    return message + '.' + signature


def test_password_salted_and_invalid():
    first = password_hash('password123')
    assert first.startswith('pbkdf2_sha256$')
    assert first != password_hash('password123')
    assert verify_password('password123', first)
    assert not verify_password('wrong', first)
    for invalid in ('', '!BOOTSTRAP_PASSWORD_REQUIRED!', 'x$bad$x$x'):
        assert not verify_password('password123', invalid)


def test_migrated_sentinel_claim_is_one_time_and_isolated(auth_app):
    from auth import SENTINEL_PASSWORD_HASH

    client = auth_app.test_client()
    with auth_app.app_context():
        con = get_db()
        con.execute(
            "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,datetime('now'))",
            ('owner', SENTINEL_PASSWORD_HASH, 'owner'),
        )
        con.execute(
            "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,datetime('now'))",
            ('user2', password_hash('user2-original'), 'member'),
        )
        con.commit()
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': '!BOOTSTRAP_PASSWORD_REQUIRED!'}).status_code == 401
    short = client.post('/api/auth/login', json={'username': 'owner', 'password': 'short'})
    assert short.status_code == 400
    claimed = client.post('/api/auth/login', json={'username': 'owner', 'password': 'owner-claim-password'})
    assert claimed.status_code == 200
    assert claimed.get_json()['data']['first_login'] is True
    assert 'HttpOnly' in claimed.headers['Set-Cookie']
    assert client.post('/api/auth/logout').status_code == 200
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': 'another-password'}).status_code == 401
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': 'owner-claim-password'}).status_code == 200
    assert client.post('/api/auth/login', json={'username': 'user2', 'password': 'new-user2-password'}).status_code == 401
    with auth_app.app_context():
        row = get_db().execute('SELECT password_hash FROM users WHERE username=?', ('user2',)).fetchone()
        assert row['password_hash'] != SENTINEL_PASSWORD_HASH


def test_bootstrap_login_cookie_logout(auth_app):
    client = auth_app.test_client()
    assert client.get('/api/auth/me').status_code == 401
    assert client.post('/api/auth/bootstrap', json={'username': 'owner', 'password': 'short'}).status_code == 400
    assert client.post('/api/auth/bootstrap', json={'username': 'owner', 'password': 'password123'}).get_json()['code'] == 0
    assert client.post('/api/auth/bootstrap', json={}).status_code == 403
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': 'wrong'}).status_code == 401
    response = client.post('/api/auth/login', json={'username': 'owner', 'password': 'password123'})
    assert response.status_code == 200
    assert 'HttpOnly' in response.headers['Set-Cookie']
    assert 'SameSite=Lax' in response.headers['Set-Cookie']
    assert client.get('/api/auth/me').get_json()['data']['username'] == 'owner'
    # 显式坏 Bearer 不得回退至有效 cookie。
    assert client.get('/api/auth/me', headers={'Authorization': 'Bearer invalid'}).status_code == 401
    assert client.get('/api/subjects').status_code == 200
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/auth/me').status_code == 401
    assert client.get('/api/subjects').status_code == 401


@pytest.mark.parametrize('changes,algorithm', [
    ({'sub': None}, 'HS256'), ({'sub': '1'}, 'HS256'),
    ({'sub': True}, 'HS256'), ({'sub': -1}, 'HS256'),
    ({'username': None}, 'HS256'), ({'role': 'admin'}, 'HS256'),
    ({'exp': 'tomorrow'}, 'HS256'), ({'exp': 0}, 'HS256'),
    ({'exp': float('nan')}, 'HS256'), ({'exp': float('inf')}, 'HS256'), ({}, 'none'),
])
def test_signed_malformed_claims_rejected(auth_app, changes, algorithm):
    claims = {'sub': 1, 'username': 'owner', 'role': 'owner', 'exp': time.time() + 60}
    claims.update(changes)
    token = signed(auth_app, claims, algorithm)
    with auth_app.app_context():
        assert decode_token(token) is None
    response = auth_app.test_client().get('/api/subjects', headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 401


def test_bearer_deleted_account_and_tampering(auth_app):
    client = auth_app.test_client()
    client.post('/api/auth/bootstrap', json={'username': 'owner', 'password': 'password123'})
    with auth_app.app_context():
        user = dict(get_db().execute('SELECT id,username,role FROM users').fetchone())
        token = issue_token(user)
        assert decode_token(token)['sub'] == user['id']
        assert decode_token(token + 'x') is None
        assert decode_token('garbage') is None
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get('/api/auth/me', headers=headers).status_code == 200
    with auth_app.app_context():
        get_db().execute('DELETE FROM users WHERE id=?', (user['id'],))
        get_db().commit()
    assert client.get('/api/auth/me', headers=headers).status_code == 401
    assert client.get('/api/subjects', headers=headers).status_code == 401


def test_fresh_schema_constraints(auth_app):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('s2_schema_gate', Path(__file__).resolve().parents[1] / 'scripts/s2_schema_assert.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    gate.assert_schema(auth_app.config['DATABASE_PATH'])


def test_anonymous_request_service_helpers_do_not_default_to_ray(auth_app):
    from services import quizgen, quota, upload
    with auth_app.test_request_context('/api/upload'):
        assert upload._uid() is None
        assert quota._uid() is None
        with pytest.raises(quizgen.QuizGenError, match='authenticated user required'):
            quizgen.card_context(get_db(), 1)
        with pytest.raises(quizgen.QuizGenError, match='authenticated user required'):
            quizgen.cached_item(get_db(), 1)


def test_private_service_helpers_reject_missing_identity(auth_app):
    from services import (
        jobs,
        progress,
        quiz,
        quota,
        report,
        review_sched,
        scope,
        streak,
        tasks,
        unlock,
        upload,
    )
    with auth_app.test_request_context('/api/private'):
        for helper in (progress._uid, quiz._uid, report._uid, scope._uid,
                       streak._uid, tasks._uid, unlock._uid):
            with pytest.raises(RuntimeError, match='authenticated user required'):
                helper()
        con = get_db()
        with pytest.raises(RuntimeError, match='authenticated user required'):
            review_sched.apply_result(con, 1, 'good')
        for call in (
            lambda: quota.quota_state(con),
            lambda: upload.find_pooled_book(con, 'hash'),
            lambda: upload.accept_upload(con, b'', 'empty.pdf', '/tmp/unused-s2'),
            lambda: jobs.transition(con, 1, 'ready', 100),
            lambda: jobs.get_job(con, 1),
        ):
            with pytest.raises(ValueError, match='authenticated user required'):
                call()


def test_explicit_mastery_identity_uses_owned_cards_only(auth_app):
    from services import progress, review_sched
    with auth_app.app_context():
        assert progress.card_metrics(get_db(), 99999, user_id=1) == {
            'm': 0, 'acc': None, 'evidence': False,
        }
        with pytest.raises(ValueError):
            review_sched.apply_result(get_db(), 1, 'invalid', user_id=1)
        assert progress._days_since('bad timestamp', '2026-10-12') is None


@pytest.mark.parametrize('apply,mechanical,stale', [
    (True, False, False), (False, False, False),
    (False, False, True), (True, True, True),
])
def test_refresh_cli_isolated_inputs(tmp_path, monkeypatch, capsys, apply, mechanical, stale):
    import sys

    from scripts import refresh_stale_quiz_items as script
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    argv = ['refresh', '--db', str(tmp_path / 'refresh.sqlite3')]
    if apply:
        argv.append('--apply')
    if mechanical:
        argv.append('--allow-mechanical')
    monkeypatch.setattr(sys, 'argv', argv)
    rows = [dict(id=1, card_id=1, type='bool', reason='language', stem='stale')] if stale else []
    monkeypatch.setattr(script, 'refresh', lambda con, apply=False: rows)
    expected = 2 if apply and not mechanical else 0
    assert script.main() == expected
    output = capsys.readouterr().out
    assert ('拒绝落地' if expected == 2 else ('1 条' if stale else '无脏题')) in output


@pytest.mark.parametrize('function,status', [
    ('e_auth', 401), ('e_role', 403), ('e_forbidden', 403),
    ('e_rate', 429), ('e_internal', 500),
])
def test_error_contract_helpers(auth_app, function, status):
    from middleware import errors
    with auth_app.app_context():
        response, actual = getattr(errors, function)()
        assert actual == status
        assert response.get_json()['msg']


def test_database_uri_validation(auth_app, monkeypatch, tmp_path):
    from data import db
    monkeypatch.delenv('DATABASE_PATH', raising=False)
    with auth_app.app_context():
        auth_app.config['DATABASE_PATH'] = None
        auth_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///relative-test.sqlite3'
        assert db._db_path().endswith('relative-test.sqlite3')
        auth_app.config['SQLALCHEMY_DATABASE_URI'] = ''
        assert db._db_path().endswith('data-local/review.sqlite3')  # 仅计算路径，不打开。
        assert db._normalize_path('sqlite:///' + str(tmp_path / 'test.sqlite3')).endswith('test.sqlite3')
        with pytest.raises(RuntimeError, match='URI host'):
            db._normalize_path('file://untrusted-host/tmp/test.sqlite3')


def test_schedule_service_rejects_other_users_card(auth_app):
    from pathlib import Path

    from services import cards, review_sched

    from scripts import ingest_kb
    with auth_app.app_context():
        con = get_db()
        con.execute("INSERT INTO users (id, username, password_hash, role, created_at) VALUES(1,'owner','test','owner','t')")
        con.execute("INSERT INTO households(id,name,created_at) VALUES(2,'别家','t')")
        con.execute("INSERT INTO users (id, username, password_hash, role, created_at) VALUES(2,'other','test','member','t')")
        con.execute('UPDATE users SET household_id=2 WHERE id=2')  # 跨户：不应看到本户卡片
        ingest_kb.ingest_file(con, Path(__file__).parent / 'fixtures/cards-contract-1.jsonl')
        before = dict(con.execute('SELECT * FROM cards WHERE id=1').fetchone())
        assert cards.card_schedule(con, 1, user_id=2).fetchone() is None
        assert review_sched.apply_result(con, 1, 'good', user_id=2) is None
        assert cards.update_card_schedule(con, 1, 999, 't', 'mastered', user_id=2).rowcount == 0
        assert dict(con.execute('SELECT * FROM cards WHERE id=1').fetchone()) == before
        assert con.execute('SELECT COUNT(*) FROM card_reviews').fetchone()[0] == 0
        assert review_sched.apply_result(con, 1, 'good', user_id=1)['learn_count'] == 1
        assert con.execute('SELECT user_id FROM card_reviews').fetchone()[0] == 1


def test_foreign_and_missing_session_and_draft_have_identical_404(auth_app):
    from services import quiz
    client = auth_app.test_client()
    client.post('/api/auth/bootstrap', json={'username': 'owner', 'password': 'password123'})
    with auth_app.app_context():
        con = get_db()
        con.execute("INSERT INTO users (id, username, password_hash, role, created_at) VALUES(2,'B','unused','member','t')")
        con.execute("INSERT INTO upload_jobs(id,book_hash,filename,pages,status,stage,created_at,updated_at,owner_id) "
                    "VALUES(1,'hash','x.pdf',1,'ready','ready','t','t',1)")
        con.execute("INSERT INTO card_drafts(id,job_id,book_hash,payload,confidence,created_at) "
                    "VALUES(1,1,'hash','{}','high','t')")
        con.commit()
        token = issue_token({'id': 2, 'username': 'B', 'role': 'member'})
    headers = {'Authorization': 'Bearer ' + token}
    session_id = 's2-foreign-session'
    quiz._SESSIONS[session_id] = {'user_id': 1, 'items': {}, 'answers': {}}
    try:
        def answer(sid):
            return client.post('/api/quiz/answer', headers=headers,
                               json={'session_id': sid, 'item_id': 1, 'my_answer': 'x'})
        foreign, missing = answer(session_id), answer('s2-absent-session')
        assert foreign.status_code == missing.status_code == 404
        assert foreign.data == missing.data
        foreign = client.put('/api/drafts/1', headers=headers, json={'status': 'kept'})
        missing = client.put('/api/drafts/999999', headers=headers, json={'status': 'kept'})
        assert foreign.status_code == missing.status_code == 404
        assert foreign.data == missing.data
        assert client.put('/api/drafts/1', headers=headers, json={'status': 'invalid'}).status_code == 400
        with auth_app.app_context():
            assert get_db().execute('SELECT status FROM card_drafts WHERE id=1').fetchone()[0] == 'kept'
    finally:
        quiz._SESSIONS.pop(session_id, None)


def test_init_db_cli_on_isolated_existing_schema(auth_app):
    result = auth_app.test_cli_runner().invoke(args=['init-db'])
    assert result.exit_code == 0
    assert 'init_db done' in result.output
