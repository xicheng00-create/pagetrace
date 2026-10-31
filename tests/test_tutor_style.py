"""作答风格三选一：explain（默认）/ brief / socratic（REQ-TUTOR-10）。"""
import pytest
from tutor_fixtures import make_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "style.sqlite3"))
    return make_app(tmp_path / "style.sqlite3")


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        yield test_client


def test_default_style_is_explain_in_prompt():
    from ai import tutor_prompts

    system = tutor_prompts.build_system({"mode": "free"})
    assert "详细解释（默认）" in system
    assert "苏格拉底引导" not in system


@pytest.mark.parametrize("style,marker", [
    ("explain", "详细解释（默认）"),
    ("brief", "简答：最多 3 句"),
    ("socratic", "苏格拉底引导：不直接给答案"),
])
def test_prompt_carries_selected_style(style, marker):
    from ai import tutor_prompts

    assert marker in tutor_prompts.build_system({"mode": "free", "style": style})


def test_unknown_style_is_rejected(client):
    response = client.post("/api/tutor/chat", json={"mode": "free", "message": "亲密伴侣暴力包括哪些行为？",
                                                    "style": "verbose"})
    assert response.status_code == 400
    assert response.get_json()["code"] == "E_INVALID_INPUT"


@pytest.mark.parametrize("style", ["explain", "brief", "socratic"])
def test_three_styles_are_accepted(client, style):
    response = client.post("/api/tutor/chat", json={"mode": "free", "message": "亲密伴侣暴力包括哪些行为？",
                                                    "style": style})
    assert response.status_code == 200
    assert response.get_json()["data"]["conversation_id"] > 0
