"""Owner-issued one-time invitations; plaintext returned only at creation."""
import secrets
from datetime import timedelta

from auth import password_hash, require_user
from data.db import get_db
from flask import Blueprint, jsonify
from services.clock import now_iso

bp = Blueprint('invites', __name__)


def owner():
    user = require_user()
    return user if user and user['role'] == 'owner' else None


@bp.post('/api/invites')
def create_invite():
    user = owner()
    if not user:
        return jsonify({'code': 403, 'msg': '只有 owner 可以生成邀請碼'}), 403
    code = secrets.token_urlsafe(24)
    from datetime import datetime
    now = datetime.fromisoformat(now_iso())
    expires = (now + timedelta(hours=24)).isoformat()
    con = get_db()
    con.execute('INSERT INTO invites(code_hash,created_by,created_at,expires_at) VALUES(?,?,?,?)',
                (password_hash(code), user['sub'], now.isoformat(), expires))
    con.commit()
    return jsonify({'code': 0, 'data': {'code': code, 'expires_at': expires}})


@bp.get('/api/invites')
def list_invites():
    user = owner()
    if not user:
        return jsonify({'code': 403, 'msg': '只有 owner 可以生成邀請碼'}), 403
    now = now_iso()
    rows = get_db().execute(
        'SELECT id,created_at,expires_at,used_at,used_by FROM invites WHERE created_by=? ORDER BY id DESC',
        (user['sub'],)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item['status'] = '已用' if row['used_at'] else '過期' if row['expires_at'] <= now else '未用'
        items.append(item)
    return jsonify({'code': 0, 'data': {'invites': items}})
