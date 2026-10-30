from auth import SENTINEL_PASSWORD_HASH, issue_token, password_hash, require_user, verify_password
from data.db import get_db
from flask import Blueprint, current_app, jsonify, make_response, request
from services.household import join_household_of, new_household

bp = Blueprint("auth", __name__)
COOKIE = "access_token"


@bp.post("/api/auth/bootstrap")
def bootstrap():
    con = get_db()
    if con.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return jsonify({"code": 403, "msg": "初始化已关闭"}), 403
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or len(password) < 8:
        return jsonify({"code": 400, "msg": "账号必填，密码至少 8 位"}), 400
    uid = con.execute(
        "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,'owner',datetime('now'))",
        (username, password_hash(password)),
    ).lastrowid
    con.execute("UPDATE users SET household_id=? WHERE id=?", (new_household(con, f"{username} 的家"), uid))
    con.commit()
    return jsonify({"code": 0, "data": {"username": username, "role": "owner"}})


@bp.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    password = str(data.get("password", ""))
    con = get_db()
    user = (
        con.execute(
            "SELECT id,username,password_hash,role FROM users WHERE username=?",
            (str(data.get("username", "")).strip(),),
        )
        .fetchone()
    )
    claimed = False
    if user and user["password_hash"] == SENTINEL_PASSWORD_HASH:
        if password == SENTINEL_PASSWORD_HASH:
            return jsonify({"code": 401, "msg": "账号或密码错误"}), 401
        if len(password) < 8:
            return jsonify({"code": 400, "msg": "首次设置密码至少需要 8 位"}), 400
        changed = con.execute(
            "UPDATE users SET password_hash=? WHERE id=? AND password_hash=?",
            (password_hash(password), user["id"], SENTINEL_PASSWORD_HASH),
        ).rowcount
        if changed != 1:
            return jsonify({"code": 401, "msg": "首次设置密码失败，请重试"}), 401
        con.commit()
        claimed = True
    elif not user or not verify_password(password, user["password_hash"]):
        return jsonify({"code": 401, "msg": "账号或密码错误"}), 401
    resp = make_response(jsonify({"code": 0, "data": {"username": user["username"], "role": user["role"], "first_login": claimed}}))
    resp.set_cookie(
        COOKIE,
        issue_token(user),
        httponly=True,
        samesite="Lax",
        secure=not current_app.config.get("DEBUG", False),
        max_age=int(current_app.config.get("JWT_TTL_HOURS", 720)) * 3600,
    )
    return resp


@bp.post("/api/auth/logout")
def logout():
    resp = make_response(jsonify({"code": 0}))
    resp.delete_cookie(COOKIE, httponly=True, samesite="Lax")
    return resp


@bp.get("/api/auth/me")
def me():
    claims = require_user()
    if not claims:
        return jsonify({"code": 401, "msg": "需要登录"}), 401
    return jsonify(
        {"code": 0, "data": {"id": claims["sub"], "username": claims["username"], "role": claims["role"]}}
    )


@bp.get('/api/auth/state')
def state():
    rows = get_db().execute('SELECT password_hash FROM users LIMIT 2').fetchall()
    return jsonify({'code': 0, 'data': {
        'needs_bootstrap': not rows,
        'needs_claim': len(rows) == 1 and rows[0]['password_hash'] == SENTINEL_PASSWORD_HASH,
    }})


@bp.post('/api/auth/register')
def register():
    import sqlite3

    from services.clock import now_iso

    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))
    code = str(data.get('code', ''))
    if not username or len(username) > 80 or len(password) < 8:
        return jsonify({'code': 400, 'msg': '账号必填（最多 80 字），密码至少 8 位'}), 400
    if len(code) > 256:
        return jsonify({'code': 401, 'msg': '邀請碼無效'}), 401
    con = get_db()
    if not code:
        # 无邀请码 → 自建一个全新小组（REQ-FAM-06）；组内成员互相可见进度。
        try:
            uid = con.execute(
                "INSERT INTO users(username,password_hash,role,created_at,share_progress) "
                "VALUES(?,?,'owner',datetime('now'),1)",
                (username, password_hash(password)),
            ).lastrowid
        except sqlite3.IntegrityError:
            return jsonify({'code': 409, 'msg': '账号已存在'}), 409
        con.execute("UPDATE users SET household_id=? WHERE id=?",
                    (new_household(con, f"{username} 的小组"), uid))
        con.commit()
        return jsonify({'code': 0, 'data': {'id': uid, 'username': username, 'household_created': True}})
    # Reserve the write transaction before validating/consuming; concurrent claimants serialize.
    con.execute('BEGIN IMMEDIATE')
    invite = next((row for row in con.execute('SELECT * FROM invites')
                   if verify_password(code, row['code_hash'])), None)
    if not invite:
        con.rollback()
        return jsonify({'code': 401, 'msg': '邀請碼無效'}), 401
    now = now_iso()
    if invite['used_at'] or invite['expires_at'] <= now:
        con.rollback()
        message = '邀請碼已使用' if invite['used_at'] else '邀請碼已過期'
        return jsonify({'code': 410, 'msg': message}), 410
    changed = con.execute(
        'UPDATE invites SET used_at=? WHERE id=? AND used_at IS NULL AND expires_at>?',
        (now, invite['id'], now)).rowcount
    if changed != 1:
        con.rollback()
        return jsonify({'code': 410, 'msg': '邀請碼已使用或已過期'}), 410
    try:
        uid = con.execute(
            "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,'member',?)",
            (username, password_hash(password), now)).lastrowid
    except sqlite3.IntegrityError:
        con.rollback()
        return jsonify({'code': 409, 'msg': '账号已存在'}), 409
    join_household_of(con, uid, invite['created_by'])
    con.execute('UPDATE invites SET used_by=? WHERE id=?', (uid, invite['id']))
    con.commit()
    user = {'id': uid, 'username': username, 'role': 'member'}
    resp = make_response(jsonify({'code': 0, 'data': {'username': username, 'role': 'member'}}))
    resp.set_cookie(COOKIE, issue_token(user), httponly=True, samesite='Lax',
                    secure=not current_app.config.get('DEBUG', False),
                    max_age=int(current_app.config.get('JWT_TTL_HOURS', 720)) * 3600)
    return resp
