"""STREAK 并发写反证：locked 时短退避重试；读接口不得因快照写失败而 500。"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import create_app
from auth import issue_token, password_hash
from data.db import get_db


class _FlakyCon:
    """前 n 次命中 streak_days 写入时抛 SQLITE_BUSY，之后放行。"""

    def __init__(self, con, fails):
        self._con = con
        self._left = fails
        self.attempts = 0

    def execute(self, sql, *a, **kw):
        if "INSERT INTO streak_days" in sql:
            self.attempts += 1
            if self._left > 0:
                self._left -= 1
                raise sqlite3.OperationalError("database is locked")
        return self._con.execute(sql, *a, **kw)

    def commit(self):
        return self._con.commit()

    def rollback(self):
        return self._con.rollback()


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "streak.sqlite3"))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.app_context():
        con = get_db()
        con.execute("INSERT INTO users(username,password_hash,role,created_at,share_progress) "
                    "VALUES('Me',?,'owner','now',1)", (password_hash("pw-123456"),))
        uid = con.execute("SELECT id FROM users WHERE username='Me'").fetchone()["id"]
        con.commit()
        token = issue_token({"id": uid, "username": "Me", "role": "owner"})
    return app, {"Authorization": "Bearer " + token}


def test_record_day_retries_through_busy(tmp_path, monkeypatch):
    app, _ = _app(tmp_path, monkeypatch)
    with app.app_context():
        from services import streak

        con = get_db()
        flaky = _FlakyCon(con, fails=2)
        streak.record_day(flaky)
        assert flaky.attempts == 3  # 失败 2 次 + 成功 1 次
        row = con.execute("SELECT review_done FROM streak_days ORDER BY day DESC LIMIT 1").fetchone()
        assert row is not None


def test_record_day_raises_after_all_retries(tmp_path, monkeypatch):
    app, _ = _app(tmp_path, monkeypatch)
    with app.app_context():
        from services import streak

        flaky = _FlakyCon(get_db(), fails=99)
        try:
            streak.record_day(flaky)
        except sqlite3.OperationalError as e:
            assert "locked" in str(e).lower()
        else:  # pragma: no cover
            raise AssertionError("六次重试后仍应抛出 locked")
        assert flaky.attempts == 6


def test_task_endpoint_survives_snapshot_failure(tmp_path, monkeypatch):
    app, h = _app(tmp_path, monkeypatch)
    from services import streak

    def boom(con, *a, **kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(streak, "record_day", boom)
    r = app.test_client().get("/api/task", headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert "review" in r.get_json()["data"]


class _BadRollbackCon(_FlakyCon):
    def rollback(self):
        raise sqlite3.OperationalError("rollback failed")


def test_record_day_survives_rollback_failure(tmp_path, monkeypatch):
    """重试期间 rollback 自身报错不得中断重试（内部吞掉）。"""
    app, _ = _app(tmp_path, monkeypatch)
    with app.app_context():
        from services import streak

        flaky = _BadRollbackCon(get_db(), fails=1)
        streak.record_day(flaky)
        assert flaky.attempts == 2


def test_record_day_reraises_non_locked_immediately(tmp_path, monkeypatch):
    """非 locked 的 OperationalError 不重试，立即抛出。"""
    app, _ = _app(tmp_path, monkeypatch)

    class _Boom:
        def __init__(self, con):
            self._con, self.attempts = con, 0

        def execute(self, sql, *a, **kw):
            if "INSERT INTO streak_days" in sql:
                self.attempts += 1
                raise sqlite3.OperationalError("no such table: streak_days")
            return self._con.execute(sql, *a, **kw)

        def commit(self):
            return self._con.commit()

        def rollback(self):
            return self._con.rollback()

    with app.app_context():
        from services import streak

        boom = _Boom(get_db())
        try:
            streak.record_day(boom)
        except sqlite3.OperationalError as e:
            assert "no such table" in str(e)
        else:  # pragma: no cover
            raise AssertionError("非 locked 错误应直接抛出")
        assert boom.attempts == 1
