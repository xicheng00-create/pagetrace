"""概念表路由（规格 §9f / 验收 A11 的代码侧）：只认完全相等的名字、失败一律静默退回、账要记全。"""
import sqlite3

import pytest
from tutor_fixtures import make_app

from ai import concept_router
from ai import rag
from ai import tutor as tutor_mod
from services import llm

STRONG = "亲密伴侣暴力包括哪些行为？"
WEAK = "他动手了我怕他"

# 三个「概念存在但没有卡」的概念：用来验证「路由给出候选、概念下无卡 → 退回 2-gram → 反问优先用路由候选」
EMPTY_CONCEPTS = """
INSERT INTO concepts(concept_uid,chapter_id,name,tags) VALUES
  ('e1',1,'空概念甲','[]'),
  ('e2',1,'空概念乙','[]'),
  ('e3',1,'空概念丙','[]');
"""


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "router.sqlite3"))
    app = make_app(tmp_path / "router.sqlite3")
    with app.app_context():
        from data.db import get_db

        con = get_db()
        con.executescript(EMPTY_CONCEPTS)
        con.commit()
    return app


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        yield test_client


def _fake(route_reply="", *, route_error=None, answer_reply="模型答复",
          route_usage=(1700, 12), answer_usage=(11, 7)):
    """假 llm.complete：按 feature 分流（tutor_route = 路由，tutor = 作答），并记下每次 feature。"""
    calls = []

    def fake(messages, **kwargs):
        feature = kwargs.get("feature")
        calls.append(feature)
        if feature == concept_router.FEATURE:
            if route_error is not None:
                raise route_error
            usage = {}
            if route_usage is not None:
                usage = {"prompt_tokens": route_usage[0], "completion_tokens": route_usage[1]}
            return route_reply, usage
        usage = {}
        if answer_usage is not None:
            usage = {"prompt_tokens": answer_usage[0], "completion_tokens": answer_usage[1]}
        return answer_reply, usage

    fake.calls = calls
    return fake


def _chat(client, **payload):
    payload.setdefault("message", STRONG)
    response = client.post("/api/tutor/chat", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["data"]


def _quota_row(app):
    from data.db import get_db

    with app.app_context():
        return get_db().execute(
            "SELECT chat_calls,tokens_in,tokens_out FROM quota_usage WHERE user_id=1").fetchone()


# ---------------------------------------------------------------- 解析口径（纯函数）

def test_parse_accepts_only_exact_names_and_strips_numbering():
    known = {"亲密伴侣暴力", "性满足", "项目管理"}
    reply = "1. 亲密伴侣暴力\n- 性满足\n2）项目管理\n"
    assert concept_router.parse(reply, known) == ["亲密伴侣暴力", "性满足", "项目管理"]


def test_parse_drops_lines_that_are_not_exact_names():
    """多一个字都不算命中：只容许「去编号 / 去行尾标点 / 去外层括号引号」三种清洗。"""
    known = {"亲密伴侣暴力", "性满足"}
    reply = ("亲密伴侣暴力\n亲密伴侣暴力（概念）\n差不多是性满足吧\n我猜你想问的是性满足。\n"
             "性满足。\n「性满足」")
    assert concept_router.parse(reply, known) == ["亲密伴侣暴力", "性满足"]


def test_parse_returns_empty_on_garbage():
    assert concept_router.parse("抱歉，我无法完成这个请求。", {"亲密伴侣暴力"}) == []
    assert concept_router.parse("", {"亲密伴侣暴力"}) == []
    assert concept_router.parse(None, {"亲密伴侣暴力"}) == []
    assert concept_router.parse("\n  \n\n", {"亲密伴侣暴力"}) == []


# ---------------------------------------------------------------- 配置与容错边角

def test_cfg_without_app_context_falls_back_to_base_config():
    assert concept_router._cfg("TUTOR_ROUTE_TIMEOUT", 8) == 8


def test_timeout_falls_back_when_config_is_not_a_number(app):
    app.config["TUTOR_ROUTE_TIMEOUT"] = "八秒"
    with app.app_context():
        assert concept_router._timeout() == concept_router.DEFAULT_TIMEOUT
    app.config["TUTOR_ROUTE_TIMEOUT"] = 0
    with app.app_context():
        assert concept_router._timeout() == concept_router.DEFAULT_TIMEOUT


def test_bad_scope_shape_is_ignored(app, monkeypatch):
    """scope 传了非 dict：不能炸，按「全可见范围」继续。"""
    monkeypatch.setattr(llm, "complete", _fake("亲密伴侣暴力"))
    with app.app_context():
        from data.db import get_db

        assert concept_router.pick(get_db(), 1, "我动手了", "全库") == ["亲密伴侣暴力"]


def test_blank_message_short_circuits(app, monkeypatch):
    fake = _fake("亲密伴侣暴力")
    monkeypatch.setattr(llm, "complete", fake)
    with app.app_context():
        from data.db import get_db

        detail = concept_router.pick_detailed(get_db(), 1, "   ", None)
    assert detail["names"] == [] and detail["empty_reason"] == "empty_message"
    assert fake.calls == []   # 空话不花模型钱


def test_empty_scope_returns_no_concepts_without_calling_model(app, monkeypatch):
    """范围收窄到没有概念（学科 2「别的」无书）：直接 no_concepts，不花模型钱。"""
    fake = _fake("亲密伴侣暴力")
    monkeypatch.setattr(llm, "complete", fake)
    with app.app_context():
        from data.db import get_db

        detail = concept_router.pick_detailed(get_db(), 1, "我动手了", {"subject_id": 2})
    assert detail["names"] == [] and detail["empty_reason"] == "no_concepts"
    assert fake.calls == []


def test_visible_concepts_error_returns_empty(app, monkeypatch):
    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(rag, "visible_concepts", boom)
    with app.app_context():
        from data.db import get_db

        detail = concept_router.pick_detailed(get_db(), 1, "我动手了", None)
    assert detail["names"] == [] and detail["empty_reason"] == "scope_error"


def test_concept_helpers_tolerate_empty_input(app):
    with app.app_context():
        from data.db import get_db

        con = get_db()
        assert concept_router.concepts_by_names(con, [], user_id=1) == []
        assert concept_router.cards_of_concepts(con, [], user_id=1) == []
        assert concept_router.cards_of_concepts(con, [1], user_id=1, top_k=0) == []
        # 同一概念下有多张卡：top_k 满即停（验证轮流取卡的短路分支）
        assert len(concept_router.cards_of_concepts(con, [1], user_id=1, top_k=1)) <= 1



def test_parse_caps_at_three_and_dedupes():
    known = {"甲概念", "乙概念", "丙概念", "丁概念"}
    reply = "甲概念\n乙概念\n甲概念\n丙概念\n丁概念"
    assert concept_router.parse(reply, known) == ["甲概念", "乙概念", "丙概念"]


# ---------------------------------------------------------------- pick()：失败一律 []

def test_pick_returns_names_on_exact_match(app, monkeypatch):
    monkeypatch.setattr(llm, "complete", _fake("亲密伴侣暴力\n性满足\n"))
    with app.app_context():
        from data.db import get_db

        assert concept_router.pick(get_db(), 1, "我动手了", None) == ["亲密伴侣暴力", "性满足"]


def test_pick_swallows_model_error(app, monkeypatch):
    monkeypatch.setattr(llm, "complete", _fake(route_error=llm.LLMError("upstream down")))
    with app.app_context():
        from data.db import get_db

        detail = concept_router.pick_detailed(get_db(), 1, "我动手了", None)
    assert detail["names"] == []
    assert detail["empty_reason"] == "llm_error"


def test_pick_swallows_timeout(app, monkeypatch):
    class Timeout(Exception):
        pass

    monkeypatch.setattr(llm, "complete", _fake(route_error=Timeout("timed out")))
    with app.app_context():
        from data.db import get_db

        assert concept_router.pick(get_db(), 1, "我动手了", None) == []


def test_pick_returns_empty_when_model_replies_garbage(app, monkeypatch):
    monkeypatch.setattr(llm, "complete", _fake("我不知道你在说什么。"))
    with app.app_context():
        from data.db import get_db

        assert concept_router.pick(get_db(), 1, "我动手了", None) == []


def test_prompt_only_contains_visible_concept_names(app, monkeypatch):
    """租户边界：给模型的清单只能是该用户看得见的概念（Bob 看不到 owner 的书）。"""
    seen = {}

    def fake(messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return "项目管理", {"prompt_tokens": 10, "completion_tokens": 1}

    monkeypatch.setattr(llm, "complete", fake)
    with app.app_context():
        from data.db import get_db

        con = get_db()
        concept_router.pick(con, 1, "这项目怎么排", None)  # owner
        ray_prompt = seen["prompt"]
        concept_router.pick(con, 3, "这项目怎么排", None)  # Bob
        bob_prompt = seen["prompt"]
    assert "亲密伴侣暴力" in ray_prompt and "项目管理" not in ray_prompt
    assert "项目管理" in bob_prompt and "亲密伴侣暴力" not in bob_prompt


# ---------------------------------------------------------------- 编排顺序

def test_free_mode_routes_first_and_answers_from_routed_concept(client, monkeypatch):
    fake = _fake("亲密伴侣暴力", answer_reply="路由答复")
    monkeypatch.setattr(llm, "complete", fake)
    data = _chat(client, message=STRONG)
    assert data["type"] == "answer" and data["reply"] == "路由答复"
    assert [source["concept"] for source in data["sources"]] == ["亲密伴侣暴力"]
    assert fake.calls == [concept_router.FEATURE, "tutor"]  # 路由 → 作答，顺序固定


def test_router_failure_falls_back_to_2gram_and_never_500(client, monkeypatch):
    """路由打桩抛异常：不 500，退回 2-gram 正常作答（A11 第二条）。"""
    monkeypatch.setattr(llm, "complete", _fake(route_error=llm.LLMError("boom"),
                                               answer_reply="模型答复"))
    data = _chat(client, message=STRONG)
    assert data["type"] == "answer"
    assert data["sources"][0]["card_id"] == 1   # 2-gram 命中的那张卡


def test_router_failure_still_charges_exactly_one_call(client, app, monkeypatch):
    monkeypatch.setattr(llm, "complete", _fake(route_error=llm.LLMError("boom")))
    _chat(client, message=STRONG)
    row = _quota_row(app)
    assert row["chat_calls"] == 1


def test_router_module_exception_falls_back_to_2gram(client, monkeypatch):
    """路由模块**自身**抛异常（不只是模型失败）：编排层要兜住，退回 2-gram 正常作答。"""
    def boom(*args, **kwargs):
        raise RuntimeError("router exploded")

    monkeypatch.setattr(concept_router, "pick_detailed", boom)
    monkeypatch.setattr(llm, "complete", _fake(answer_reply="模型答复"))
    data = _chat(client, message=STRONG)
    assert data["type"] == "answer"
    assert data["sources"][0]["card_id"] == 1


def test_card_mode_does_not_route(client, monkeypatch):
    fake = _fake("亲密伴侣暴力")
    monkeypatch.setattr(llm, "complete", fake)
    data = _chat(client, mode="card", card_id=1, message="讲讲这张卡")
    assert data["type"] == "answer"
    assert concept_router.FEATURE not in fake.calls


def test_clarify_options_prefer_routed_candidates(client, monkeypatch):
    """路由给出 3 个候选但这些概念下没卡 → 退回 2-gram（弱命中）→ 反问，候选用路由那 3 个。"""
    monkeypatch.setattr(llm, "complete", _fake("空概念甲\n空概念乙\n空概念丙"))
    data = _chat(client, message=WEAK)
    assert data["type"] == "clarify"
    assert [option["name"] for option in data["options"]][:3] == ["空概念甲", "空概念乙", "空概念丙"]


# ---------------------------------------------------------------- 账

def test_route_tokens_are_added_to_the_answer_turn(client, app, monkeypatch):
    monkeypatch.setattr(llm, "complete", _fake("亲密伴侣暴力", answer_reply="路由答复",
                                               route_usage=(1700, 12), answer_usage=(11, 7)))
    data = _chat(client, message=STRONG)
    assert (data["tokens_in"], data["tokens_out"]) == (1711, 19)
    row = _quota_row(app)
    assert (row["chat_calls"], row["tokens_in"], row["tokens_out"]) == (1, 1711, 19)


def test_clarify_turn_records_route_tokens_without_charging_quota(client, app, monkeypatch):
    monkeypatch.setattr(llm, "complete", _fake("无", route_usage=(1700, 3)))
    data = _chat(client, message=WEAK)
    assert data["type"] == "clarify"
    assert (data["tokens_in"], data["tokens_out"]) == (1700, 3)
    row = _quota_row(app)
    assert row is not None and row["chat_calls"] == 0   # 记 token ≠ 记一次调用
    assert (row["tokens_in"], row["tokens_out"]) == (1700, 3)


def test_quota_exhausted_returns_429_before_routing(client, app, monkeypatch):
    """次数已用尽时先 429，不再花钱打路由（否则被拒的请求也照扣 token）。"""
    app.config["TUTOR_DAILY_LIMIT"] = 1
    fake = _fake("亲密伴侣暴力")
    monkeypatch.setattr(llm, "complete", fake)
    assert _chat(client, message=STRONG)["type"] == "answer"
    calls_before = list(fake.calls)
    response = client.post("/api/tutor/chat", json={"message": STRONG})
    assert response.status_code == 429
    assert response.get_json()["code"] == "E_QUOTA"
    assert fake.calls == calls_before   # 第 41 次（此处第 2 次）一次模型都没打
