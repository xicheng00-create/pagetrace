"""澄清反问（规格 §9e）：弱命中必反问、点选后在该概念下作答、反问不扣配额、两次选不出直说库里没有。

对应验收 A9 / A10（`~/AgentMemory/projects/xueer-tutor-spec.md` §10）。
"""
import pytest
from tutor_fixtures import bearer, make_app, token_for

from ai import rag
from ai import tutor as tutor_mod

# 追加 3 个概念 + 3 张卡：让「他动手了我怕他」这一句在别名臂上能落到 ≥3 个概念候选
# （主库有大量这类概念，测试库要自己补齐，否则「不足 3 个不反问」会直接被触发）。
EXTRA = """
INSERT INTO concepts(concept_uid,chapter_id,name,tags) VALUES
  ('c1',1,'亲密恐吓','["概念"]'),
  ('c2',1,'情境型伴侣暴力','["概念"]'),
  ('c3',1,'受害者不离开的原因','["概念"]');
INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,created_at) VALUES
  (4,1,'亲密恐吓的核心是什么？','以威胁与恐吓控制伴侣','src','c1h',datetime('now')),
  (5,1,'情境型伴侣暴力是什么？','由情境激起的暴力，多见于被激怒的一方','src','c2h',datetime('now')),
  (6,1,'受害者为什么不离开？','恐惧、经济依赖与社会支持缺失','src','c3h',datetime('now'));
"""

WEAK = "他动手了我怕他"      # 主臂 0 命中、别名臂有落地（表内口语句）
STRONG = "亲密伴侣暴力包括哪些行为？"


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = tmp_path / "clarify.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    app = make_app(path)
    with app.app_context():
        from data.db import get_db

        con = get_db()
        con.executescript(EXTRA)
        con.commit()
    return app


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        yield test_client


def _chat(client, **payload):
    payload.setdefault("message", WEAK)
    return client.post("/api/tutor/chat", json=payload).get_json()["data"]


def _quota(app, username="owner"):
    from data.db import get_db

    with app.app_context():
        row = get_db().execute(
            "SELECT chat_calls FROM quota_usage WHERE user_id="
            "(SELECT id FROM users WHERE username=?)", (username,)).fetchone()
    return row[0] if row else 0


def test_weak_hit_is_weak_by_definition(app):
    """口径锚点：这句在主臂上覆盖率低于阈值（否则下面的用例测的就不是弱命中）。"""
    from data.db import get_db

    with app.app_context():
        con = get_db()
        user_id = con.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
        picked = rag.pick(con, WEAK, user_id=user_id)
    assert picked["top_coverage"] < rag.WEAK_COVERAGE
    assert picked["weak"] is True
    assert len(picked["options"]) >= rag.CLARIFY_MIN_OPTIONS


def test_a9_weak_hit_asks_back_and_does_not_charge_quota(client, app):
    """A9 前半：弱命中 → type=clarify + 3–5 个 options + 配额不动。"""
    data = _chat(client)
    assert data["type"] == "clarify"
    assert data["question"] == tutor_mod.CLARIFY_QUESTION
    assert 3 <= len(data["options"]) <= 5
    assert all({"concept_id", "name"} <= set(option) for option in data["options"])
    assert data["conversation_id"] > 0
    assert data["quota"]["used"] == 0 and _quota(app) == 0  # 反问不扣次数
    assert data["sources"] == []


def test_a9_pick_concept_answers_from_that_concept(client, app):
    """A9 后半：带选中 concept_id 重发 → 直接在该概念下取卡作答，此时才扣一次。"""
    first = _chat(client)
    option = first["options"][0]
    data = _chat(client, conversation_id=first["conversation_id"],
                 concept_id=option["concept_id"])
    assert data["type"] == "answer"
    assert data["sources"], "必须引用卡片"
    assert {source["concept"] for source in data["sources"]} == {option["name"]}, \
        "只允许引用被点选概念下的卡"
    assert _quota(app) == 1  # 真正作答才扣
    assert "question" not in data and "options" not in data  # 作答回合不带澄清字段


def test_pick_concept_skips_retrieval_even_with_weak_message(client):
    """点选即定概念：同一句弱口语，带 concept_id 时不再反问。"""
    first = _chat(client)
    target = first["options"][-1]
    data = _chat(client, message=WEAK, conversation_id=first["conversation_id"],
                 concept_id=target["concept_id"])
    assert data["type"] == "answer"
    assert all(source["concept"] == target["name"] for source in data["sources"])


def test_a10_two_clarifies_then_says_nothing_matched(client, app):
    """A10：连续两次澄清仍选不出 → 明说「库里没找到贴合的页」，且不编造、不扣次数。"""
    first = _chat(client)
    assert first["type"] == "clarify"
    conversation_id = first["conversation_id"]

    second = _chat(client, conversation_id=conversation_id)
    assert second["type"] == "clarify"  # 第二次仍可反问
    assert second["conversation_id"] == conversation_id

    third = _chat(client, conversation_id=conversation_id)
    assert third["type"] == "not_found"
    assert "库里没找到贴合的页" in third["reply"]
    assert third["sources"] == []           # 不编造引用
    assert third["fallback"] is True
    assert _quota(app) == 0                 # 全程没有真正作答 → 一次都没扣


def test_picked_concept_without_cards_says_not_found(client, app):
    """点选的概念下没有卡：直说库里没有，不拿别的概念的卡顶替。"""
    from data.db import get_db

    with app.app_context():
        con = get_db()
        empty_id = con.execute(
            "INSERT INTO concepts(concept_uid,chapter_id,name,tags)"
            " VALUES('u9',1,'空概念', '[]')").lastrowid
        con.commit()
    first = _chat(client)
    data = _chat(client, conversation_id=first["conversation_id"], concept_id=empty_id)
    assert data["type"] == "not_found"
    assert data["sources"] == []
    assert _quota(app) == 0


def test_strong_query_never_asks_back(client):
    """主臂覆盖率 ≥ 阈值时不反问：口径不能被澄清机制带偏。"""
    data = _chat(client, message=STRONG)
    assert data["type"] == "answer"
    assert data["sources"][0]["card_id"] == 1


def test_card_mode_never_asks_back(client):
    """mode=card 自带卡，不需要澄清。"""
    data = _chat(client, mode="card", card_id=1, message=WEAK)
    assert data["type"] == "answer"
    assert data["sources"][0]["card_id"] == 1


def test_foreign_concept_is_404_and_free_of_quota(client, app):
    """概念点选也走租户边界：拿别人家的 concept_id → 404，且不扣次数。"""
    with app.app_context():
        bob = bearer(token_for(app, "Bob"))
    response = client.post("/api/tutor/chat", json={"message": WEAK, "concept_id": 1}, headers=bob)
    assert response.status_code == 404
    assert response.get_json()["code"] == "E_NOT_FOUND"
    assert _quota(app, "Bob") == 0


def test_clarify_turn_is_visible_in_history(client):
    """反问写进会话（否则无法数「连续澄清了几次」），且成对出现。"""
    first = _chat(client)
    listed = client.get(
        f"/api/tutor/conversations/{first['conversation_id']}/messages").get_json()["data"]
    roles = [row["role"] for row in listed["messages"]]
    assert roles == ["user", "assistant"]
    assert listed["messages"][1]["content"].startswith(tutor_mod.CLARIFY_PREFIX)


def test_clarify_rounds_reset_after_a_real_answer(client):
    """一次正常作答后，「连续澄清」计数归零（不会因为历史澄清被永久判死）。"""
    first = _chat(client)
    _chat(client, conversation_id=first["conversation_id"],
          concept_id=first["options"][0]["concept_id"])  # 正常作答
    again = _chat(client, conversation_id=first["conversation_id"])
    assert again["type"] == "clarify"
