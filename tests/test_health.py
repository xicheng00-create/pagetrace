"""冒烟测试：/health、静态首页、SW 不缓存、建表到位。

跑法：.venv/bin/pytest -q（或 make test）
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app, version  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.sqlite3"))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ok"
    assert body["data"]["db"] == "ok"
    assert body["data"]["version"] == version
    assert body["data"]["contract_version"] == 1


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "个人复习" in r.get_data(as_text=True)


def test_sw_not_cached(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("Cache-Control", "")


def test_unknown_path_is_json_404(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.get_json()["code"] == 404


def test_schema_tables_created(client):
    from data.db import get_db

    with client.application.app_context():
        rows = get_db().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    names = {row[0] for row in rows}
    assert {
        "subjects",
        "books",
        "chapters",
        "concepts",
        "cards",
        "card_reviews",
        "ingest_runs",
        "reminder_log",
        "users",
    } <= names
