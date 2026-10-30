"""测试运行隔离、临时上传账本及 legacy HTTP 测试租户。"""

import pytest


@pytest.fixture(autouse=True)
def isolated_usage_ledger(tmp_path, monkeypatch, request):
    monkeypatch.setenv("S2_OWNER_USERNAME", "owner")
    monkeypatch.setenv("REVIEW_ISOLATED_RUN", "1")
    monkeypatch.setenv("UPLOAD_WORKER_ENABLED", "0")
    monkeypatch.setenv("UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "default.sqlite3"))
    from services import llm

    monkeypatch.setattr(llm, "usage_path", lambda: tmp_path / "reviewapp.jsonl")

    # S2 以前的 HTTP 契约测试默认代表已登录的 owner；认证专测保留匿名语义。
    if request.node.fspath.basename.startswith("test_s2_"):
        yield
        return
    from flask.testing import FlaskClient

    original_open = FlaskClient.open
    authenticated = set()

    def open_authenticated(client, *args, **kwargs):
        path = args[0] if args else kwargs.get("path", "")
        if (
            isinstance(path, str)
            and path.startswith("/api/")
            and not path.startswith("/api/auth/")
            and client not in authenticated
        ):
            with client.application.app_context():
                from auth import password_hash
                from data.db import get_db

                con = get_db()
                row = con.execute("SELECT id FROM users WHERE username='owner'").fetchone()
                if row is None:
                    con.execute(
                        "INSERT INTO users(username,password_hash,role,created_at) VALUES('owner',?,'owner',datetime('now'))",
                        (password_hash("test-password"),),
                    )
                else:
                    con.execute(
                        "UPDATE users SET password_hash=? WHERE username='owner'",
                        (password_hash("test-password"),),
                    )
                con.commit()
            original_open(
                client,
                "/api/auth/login",
                method="POST",
                json={"username": "owner", "password": "test-password"},
            )
            authenticated.add(client)
        return original_open(client, *args, **kwargs)

    monkeypatch.setattr(FlaskClient, "open", open_authenticated)
    yield
    authenticated.clear()


@pytest.fixture(autouse=True)
def legacy_service_tenant_context(request, isolated_usage_ledger):
    """旧单用户服务契约明确在 owner 的应用上下文执行；S2 安全测试不使用它。"""
    suites = {
        "test_plan.py",
        "test_progress.py",
        "test_queue_group.py",
        "test_report.py",
        "test_scope.py",
        "test_streak_snapshot.py",
        "test_weak.py",
        "test_quizgen_unit.py",
        "test_quiz_refresh.py",
        "test_jobs.py",
    }
    if (
        request.node.fspath.basename not in suites
        or request.node.name == "test_cfg_falls_back_to_environ_outside_app_context"
    ):
        yield
        return
    from app import create_app
    from flask import g

    app = create_app("development")
    with app.app_context():
        g.user_id = 1
        yield


@pytest.fixture
def video_client(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1] / "backend"
    sys.path.insert(0, str(backend))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "video-test.sqlite3"))
    from app import create_app

    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client
