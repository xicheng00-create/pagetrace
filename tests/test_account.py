"""REQ-ACCT-01：账号页数据只取本人；改密码必须验旧密码。

反证：错旧密码 → 400 且密码不变；新密码 <8 位 → 400；成功后旧密码登不进、新密码可登。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import create_app
from auth import issue_token, password_hash
from data.db import get_db


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "account.sqlite3"))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.app_context():
        con = get_db()
        con.execute("INSERT INTO users(username,password_hash,role,created_at,share_progress) "
                    "VALUES('Me',?,'owner','now',1)", (password_hash("old-pass-123"),))
        uid = con.execute("SELECT id FROM users WHERE username='Me'").fetchone()["id"]
        con.commit()
        token = issue_token({"id": uid, "username": "Me", "role": "owner"})
    return app.test_client(), {"Authorization": "Bearer " + token}, uid


def test_account_shows_only_my_progress(tmp_path, monkeypatch):
    client, h, _ = _client(tmp_path, monkeypatch)
    d = client.get("/api/account", headers=h).get_json()["data"]
    assert d["username"] == "Me" and d["shared"] is True
    assert set(d["today"]) >= {"video", "review", "quiz", "done"}
    assert d["today"]["video"]["target"] == 5
    assert d["today"]["review"]["target"] <= 20  # 库里没有卡时按可用数收敛
    assert d["coverage"] == 0 and d["streak"] == 0


def test_change_password_requires_current(tmp_path, monkeypatch):
    client, h, _ = _client(tmp_path, monkeypatch)
    bad = client.post("/api/account/password", json={"current_password": "wrong", "new_password": "new-pass-123"}, headers=h)
    assert bad.status_code == 400
    short = client.post("/api/account/password", json={"current_password": "old-pass-123", "new_password": "short"}, headers=h)
    assert short.status_code == 400
    ok = client.post("/api/account/password", json={"current_password": "old-pass-123", "new_password": "new-pass-123"}, headers=h)
    assert ok.status_code == 200
    assert client.post("/api/auth/login", json={"username": "Me", "password": "old-pass-123"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "Me", "password": "new-pass-123"}).status_code == 200


def test_account_survives_locked_streak_snapshot(tmp_path, monkeypatch):
    """读路径反证：连胜快照写库失败（database is locked）不得让 /api/account 500。"""
    client, h, _ = _client(tmp_path, monkeypatch)
    import services.streak as streak_mod
    real = streak_mod.compute

    def boom(con, *a, **kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(streak_mod, "compute", boom)
    r = client.get("/api/account", headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["data"]["streak"] == 0
    monkeypatch.setattr(streak_mod, "compute", real)
