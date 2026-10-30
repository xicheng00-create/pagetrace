"""并发写反证：多线程同时打写接口，不得出现 SQLITE_BUSY 的 500。

waitress 多线程下「读事务升级为写」会立即返回 database is locked（busy_timeout 无效），
靠 app 内写请求串行化保证。本测试用 6 线程并发 POST 验证不 500。
"""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import create_app
from auth import issue_token, password_hash
from data.db import get_db
from werkzeug.test import Client  # 绕过 conftest 对 FlaskClient.open 的自动登录补丁（线程安全）


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "concurrent.sqlite3"))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.app_context():
        con = get_db()
        con.execute("INSERT INTO users(username,password_hash,role,created_at,share_progress) "
                    "VALUES('Race',?,'owner','now',1)", (password_hash("pw-123456"),))
        uid = con.execute("SELECT id FROM users WHERE username='Race'").fetchone()["id"]
        con.commit()
        token = issue_token({"id": uid, "username": "Race", "role": "owner"})
    return app, {"Authorization": "Bearer " + token}


def test_concurrent_writes_do_not_500(tmp_path, monkeypatch):
    app, headers = _setup(tmp_path, monkeypatch)
    results = []
    lock = threading.Lock()

    def hit():
        r = Client(app).post("/api/quiz/session", json={}, headers=headers)
        with lock:
            results.append((r.status_code, r.get_data(as_text=True)[:120]))

    threads = [threading.Thread(target=hit) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    codes = [c for c, _ in results]
    assert len(codes) == 6
    assert all(c == 200 for c in codes), results


def test_read_is_not_serialized(tmp_path, monkeypatch):
    """GET 不拿写锁：读接口在并发下仍然全部成功。"""
    app, headers = _setup(tmp_path, monkeypatch)
    codes = []
    lock = threading.Lock()

    def hit():
        r = Client(app).get("/api/subjects", headers=headers)
        with lock:
            codes.append(r.status_code)

    threads = [threading.Thread(target=hit) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200] * 6
