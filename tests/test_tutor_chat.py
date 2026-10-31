"""HTTP 契约：四场景、会话追加、跨用户 404（A4）、每日配额 429（A5）、模型降级。"""
import pytest
from tutor_fixtures import bearer, make_app, token_for

from ai import tutor as tutor_mod
from services import llm


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "chat.sqlite3"))
    return make_app(tmp_path / "chat.sqlite3")


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        yield test_client


def _chat(client, **payload):
    payload.setdefault("message", "亲密伴侣暴力包括哪些行为？")
    return client.post("/api/tutor/chat", json=payload)


def _quota(app, username="owner"):
    from data.db import get_db

    with app.app_context():
        row = get_db().execute("SELECT chat_calls FROM quota_usage WHERE user_id="
                               "(SELECT id FROM users WHERE username=?)", (username,)).fetchone()
    return row[0] if row else 0


def test_free_chat_persists_and_counts_quota(client, app):
    response = _chat(client, mode="free")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["conversation_id"] > 0 and data["mode"] == "free"
    assert data["reply"].strip()
    assert data["sources"][0]["card_id"] == 1
    assert data["quota"]["used"] == 1
    listed = client.get(f"/api/tutor/conversations/{data['conversation_id']}/messages").get_json()["data"]
    assert [row["role"] for row in listed["messages"]] == ["user", "assistant"]
    assert _quota(app) == 1


def test_chat_appends_to_existing_conversation(client):
    first = _chat(client).get_json()["data"]
    second = _chat(client, conversation_id=first["conversation_id"], message="再举一个例子").get_json()["data"]
    assert second["conversation_id"] == first["conversation_id"]
    listed = client.get(f"/api/tutor/conversations/{first['conversation_id']}/messages").get_json()["data"]
    assert len(listed["messages"]) == 4


def test_card_mode_needs_card_id(client):
    response = _chat(client, mode="card")
    assert response.status_code == 400
    assert response.get_json()["code"] == "E_INVALID_INPUT"
    # 反过来：带了 card_id 就可以不打字（贴卡讲解场景）
    assert _chat(client, mode="card", card_id=1, message="").status_code == 200


def test_card_mode_puts_the_card_first(client):
    data = _chat(client, mode="card", card_id=2).get_json()["data"]  # 不带 message：贴卡讲解默认问法
    assert data["sources"][0]["card_id"] == 2
    assert data["sources"][0]["concept"] == "性满足"


def test_invisible_card_is_404_and_free_of_quota(client, app):
    response = _chat(client, mode="card", card_id=3)  # 户 2 的卡
    assert response.status_code == 404
    assert response.get_json()["code"] == "E_NOT_FOUND"
    assert _quota(app) == 0


def test_quiz_and_plan_modes_run(client, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda messages, **kwargs: (None, {}))  # 模型不可用
    quiz = _chat(client, mode="quiz", message="给我出一道题").get_json()["data"]
    plan = _chat(client, mode="plan", message="今天学什么").get_json()["data"]
    assert quiz["mode"] == "quiz" and plan["mode"] == "plan"
    assert quiz["reply"].strip() and plan["reply"].strip()
    assert quiz["fallback"] is True  # 无模型：走库内兜底，不 500


def test_foreign_conversation_is_404_and_nothing_written(client, app):
    """A4：另一个账号拿别人的 conversation_id 必须 404，且原会话一条消息都不多。"""
    mine = _chat(client).get_json()["data"]
    bob = bearer(token_for(app, "Bob"))
    before = client.get(f"/api/tutor/conversations/{mine['conversation_id']}/messages").get_json()["data"]
    response = client.post("/api/tutor/chat", json={
        "message": "我是 Bob", "conversation_id": mine["conversation_id"]}, headers=bob)
    assert response.status_code == 404
    assert response.get_json()["code"] == "E_NOT_FOUND"
    listed = client.get(f"/api/tutor/conversations/{mine['conversation_id']}/messages",
                        headers=bob)
    assert listed.status_code == 404
    after = client.get(f"/api/tutor/conversations/{mine['conversation_id']}/messages").get_json()["data"]
    assert len(after["messages"]) == len(before["messages"]) == 2
    assert _quota(app, "Bob") == 0


def test_quota_endpoint_shape(client):
    data = client.get("/api/tutor/quota").get_json()["data"]
    assert data["limit"] == 40  # .env 起值
    assert data["used"] == 0 and data["remaining"] == 40
    assert data["label"] == "今天已用 0 / 40 次"


def test_validation_errors(client):
    assert _chat(client, message="").status_code == 400
    assert _chat(client, mode="nope").status_code == 400
    assert _chat(client, message="x" * 4001).status_code == 400
    assert _chat(client, conversation_id="7").get_json()["code"] == "E_INVALID_INPUT"
    assert client.post("/api/tutor/chat", data="not json",
                       content_type="application/json").status_code == 400


def test_llm_answer_and_token_accounting(client, app, monkeypatch):
    monkeypatch.setattr(llm, "complete",
                        lambda messages, **kwargs: ("库内答案", {"prompt_tokens": 11,
                                                             "completion_tokens": 7}))
    data = _chat(client).get_json()["data"]
    assert data["fallback"] is False and data["reply"] == "库内答案"
    assert (data["tokens_in"], data["tokens_out"]) == (11, 7)
    from data.db import get_db

    with app.app_context():
        row = get_db().execute("SELECT tokens_in,tokens_out FROM quota_usage").fetchone()
        assert (row["tokens_in"], row["tokens_out"]) == (11, 7)


def test_llm_failure_falls_back_to_library(client, monkeypatch):
    def boom(*_args, **_kwargs):
        raise llm.LLMError("upstream down")

    monkeypatch.setattr(llm, "complete", boom)
    data = _chat(client).get_json()["data"]
    assert data["fallback"] is True
    assert "模型暂时不可用" in data["reply"]


def test_daily_limit_429(client, app):
    """A5：每天 40 次（此处压到 2 次验证边界）。"""
    app.config["TUTOR_DAILY_LIMIT"] = 2
    assert _chat(client).status_code == 200
    assert _chat(client).status_code == 200
    response = _chat(client)
    assert response.status_code == 429
    assert response.get_json() == {"code": "E_QUOTA", "msg": "今天的 tutor 次数用完了，明天再来"}
    assert _quota(app) == 2  # 被拒的请求不虚增配额
    assert client.get("/api/tutor/quota").get_json()["data"]["remaining"] == 0


def test_limit_is_read_from_config_not_hardcoded(app):
    from flask import current_app

    with app.app_context():
        assert current_app.config["TUTOR_DAILY_LIMIT"] == 40
    assert tutor_mod.MODES == ("card", "free", "quiz", "plan")
