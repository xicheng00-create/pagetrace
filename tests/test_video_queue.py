import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from api import videos  # noqa: E402


def _seed(video_client):
    from auth import password_hash

    with video_client.application.app_context():
        from data.db import get_db

        con = get_db()
        con.executescript("""
        INSERT INTO users(username,password_hash,created_at) VALUES('owner','x',datetime('now'));
        INSERT INTO subjects(name,slug,created_at) VALUES('s','s',datetime('now'));
        INSERT INTO books(subject_id,title,slug,status,created_at,owner_id) VALUES(1,'b','b','active',datetime('now'),1);
        INSERT INTO chapters(book_id,name,anchor,unlocked_at,status) VALUES(1,'c','c',datetime('now'),'active');
        INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('a',1,'a');
        INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,created_at) VALUES(1,1,'front','back','source','hash',datetime('now'));
        """)
        con.execute("UPDATE users SET password_hash=? WHERE username='owner'", (password_hash("password"),))
        con.commit()
    video_client.post("/api/auth/login", json={"username": "owner", "password": "password"})


def test_schema_enforces_unique_core_card(video_client):
    with video_client.application.app_context():
        from data.db import get_db

        indexes = get_db().execute("PRAGMA index_list(card_videos)").fetchall()
        assert any(
            row["unique"]
            and any(
                column["name"] == "core_card_id"
                for column in get_db().execute(f"PRAGMA index_info({row['name']})")
            )
            for row in indexes
        )


def test_capability_reason(video_client, monkeypatch):
    monkeypatch.setattr(videos, "missing", lambda: ["videokit"])
    response = video_client.get("/api/videos/capability")
    assert response.json == {"code": 0, "data": {"available": False, "reason": "未检测到 VideoKit（设置 VIDEOKIT_HOME）"}}


def test_capability_reports_missing_render_deps(video_client, monkeypatch):
    monkeypatch.setattr(videos, "missing", lambda: ["manim", "edge-tts"])
    response = video_client.get("/api/videos/capability")
    assert response.json == {"code": 0, "data": {"available": False, "reason": "缺少渲染依赖：manim 或 edge-tts"}}


def test_capability_falls_back_to_absolute_paths(monkeypatch):
    """web 进程 PATH 里没有 manim/edge-tts，必须能在绝对路径上判到，否则永远置灰。"""
    monkeypatch.setattr(videos.shutil, "which", lambda _name: None)
    monkeypatch.setattr(videos.Path, "is_file", lambda self: True)
    assert videos.missing() == []


def test_request_idempotence_and_failed_reentry(video_client, monkeypatch):
    _seed(video_client)
    monkeypatch.setattr(videos, "available", lambda: True)
    for _ in range(3):
        assert video_client.post("/api/videos/request", json={"card_id": 1}).status_code == 200
    with video_client.application.app_context():
        from data.db import get_db

        con = get_db()
        assert con.execute("select count(*) from card_videos").fetchone()[0] == 1
        assert con.execute("select status from card_videos").fetchone()[0] == "queued"
        con.execute("update card_videos set status='failed',error='oops' where core_card_id=1")
        con.commit()
    assert video_client.post("/api/videos/request", json={"card_id": 1}).status_code == 200
    with video_client.application.app_context():
        from data.db import get_db

        assert get_db().execute("select status from card_videos").fetchone()[0] == "queued"


def test_batch_limit_and_locked_card(video_client, monkeypatch):
    monkeypatch.setattr(videos, "available", lambda: False)
    assert video_client.post("/api/videos/batch", json={"card_ids": list(range(11))}).status_code == 400
    assert video_client.post("/api/videos/request", json={"card_id": -1}).status_code == 404


def test_batch_success_state_list_detail_and_ready_url(video_client, monkeypatch):
    _seed(video_client)
    monkeypatch.setattr(videos, "available", lambda: True)
    result = video_client.post("/api/videos/batch", json={"card_ids": [1]})
    assert result.status_code == 200 and result.json["data"]["items"][0]["status"] == "queued"
    state = video_client.get("/api/videos/state?card_id=1").json["data"]
    assert state["status"] == "queued" and state["requested_at"]
    assert video_client.get("/api/videos").json["data"]["items"][0]["status"] == "queued"
    with video_client.application.app_context():
        from data.db import get_db

        con = get_db()
        con.execute("UPDATE card_videos SET status='ready',file_name='1.mp4',duration_s=90 WHERE id=1")
        con.commit()
    state = video_client.get("/api/videos/state?card_id=1").json["data"]
    assert state["url"] == "/media/videos/1.mp4"
    assert video_client.get("/api/videos/1").json["data"]["cards"][0]["is_core"] == 1
    assert video_client.get("/api/videos/999").status_code == 404
    assert video_client.get("/api/videos/state?card_id=999").status_code == 404


def test_batch_rejects_non_list(video_client):
    assert video_client.post("/api/videos/batch", json={"card_ids": "1"}).status_code == 400


def test_missing_dependency_returns_unavailable(video_client, monkeypatch):
    _seed(video_client)
    monkeypatch.setattr(videos, "available", lambda: False)
    response = video_client.post("/api/videos/request", json={"card_id": 1})
    assert response.status_code == 503 and response.json["code"] == 503


def test_all_json_endpoints_use_code_envelope(video_client, monkeypatch):
    """前端 api.js 只认 {code,data}；视频接口返裸对象会让 #/videos 与「讲解」静默失败。"""
    _seed(video_client)
    monkeypatch.setattr(videos, "available", lambda: True)
    for path in ("/api/videos/capability", "/api/videos", "/api/videos/state?card_id=1"):
        body = video_client.get(path).json
        assert body["code"] == 0 and "data" in body, path
    assert video_client.post("/api/videos/request", json={"card_id": 1}).json["code"] == 0
