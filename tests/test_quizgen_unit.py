"""出题器 `services/quizgen.py` 的单元断言（补足分支覆盖 + QUIZ-003 校验口径）。

- `_chat` 用 stub `requests` 注入，**不触网**：覆盖「无 key / 5xx / 抛异常 / 正常」四条路径。
- `_validate` 反向断言：类型不符 / 无选项 / 答案不在选项 / bool 选项非 [对,错] → 一律拒绝（走降级）。
"""
import json
import logging
import sys
import types
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402
from services import quizgen  # noqa: E402


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "gen.sqlite3"))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.app_context():
        yield app


class _Resp:
    def __init__(self, status=200, payload=None, raise_exc=None):
        self.status_code = status
        self._payload = payload
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise:
            raise self._raise

    def json(self):
        return self._payload


def _stub_requests(post):
    return types.SimpleNamespace(post=post)


def test_cfg_falls_back_to_environ_outside_app_context(monkeypatch):
    monkeypatch.setenv("QUIZGEN_TEST_CFG", "from-env")
    from flask import has_app_context
    assert not has_app_context()
    assert quizgen._cfg("QUIZGEN_TEST_CFG", "d") == "from-env"
    assert quizgen._cfg("QUIZGEN_TEST_CFG_MISSING", "d") == "d"


def test_chat_returns_none_without_api_key(app_env, monkeypatch):
    # proxy 档取 LLM_API_KEY（app.config 已在 create_app 时定型），显式清掉才等于「无 key」。
    app_env.config["DEEPSEEK_API_KEY"] = ""
    app_env.config["LLM_API_KEY"] = ""
    assert quizgen._chat([{"role": "user", "content": "x"}]) is None


def test_chat_returns_content_on_success(app_env, monkeypatch):
    app_env.config["LLM_API_KEY"] = "k"
    app_env.config["LLM_MODEL"] = "m"
    app_env.config["LLM_BASE_URL"] = "http://localhost:4000/"
    calls = {}

    def post(url, **kw):
        calls["url"] = url
        return _Resp(200, {"choices": [{"message": {"content": "你好"}}]})

    monkeypatch.setitem(sys.modules, "requests", _stub_requests(post))
    assert quizgen._chat([{"role": "user", "content": "x"}]) == "你好"
    assert calls["url"] == "http://localhost:4000/chat/completions"


def test_chat_returns_none_on_5xx(app_env, monkeypatch):
    app_env.config["LLM_API_KEY"] = "k"
    monkeypatch.setitem(sys.modules, "requests", _stub_requests(lambda *a, **k: _Resp(500)))
    assert quizgen._chat([{"role": "user", "content": "x"}]) is None


def test_chat_returns_none_on_exception(app_env, monkeypatch):
    app_env.config["LLM_API_KEY"] = "k"

    def boom(*a, **k):
        raise RuntimeError("网络炸了")

    monkeypatch.setitem(sys.modules, "requests", _stub_requests(boom))
    assert quizgen._chat([{"role": "user", "content": "x"}]) is None


def test_validate_rejects_bad_items():
    ok = {"type": "choice", "stem": "题", "options": ["甲", "乙"], "answer_key": "甲"}
    assert quizgen._validate(ok, "choice")["source"] == "ai"
    assert quizgen._validate(None, "choice") is None
    assert quizgen._validate({"type": "open", "stem": "s", "options": ["a", "b"],
                              "answer_key": "a"}, "choice") is None          # 类型不符
    assert quizgen._validate({"type": "choice", "stem": "", "options": ["a", "b"],
                              "answer_key": "a"}, "choice") is None          # 空题干
    assert quizgen._validate({"type": "choice", "stem": "s", "options": ["a"],
                              "answer_key": "a"}, "choice") is None          # 选项 <2
    assert quizgen._validate({"type": "choice", "stem": "s", "options": ["a", "b"],
                              "answer_key": "c"}, "choice") is None          # key 不在选项
    assert quizgen._validate({"type": "bool", "stem": "s", "options": ["真", "假"],
                              "answer_key": "真"}, "bool") is None           # bool 选项非 [对,错]


def test_parse_json_bad_object_returns_none():
    assert quizgen._parse_json("前缀 {这不是 json} 后缀") is None


def test_assign_types_zero_ratio_defaults_all_choice(monkeypatch):
    monkeypatch.setattr(quizgen.BaseConfig, "QUIZ_CHOICE_RATIO", 0)
    monkeypatch.setattr(quizgen.BaseConfig, "QUIZ_BOOL_RATIO", 0)
    assert quizgen.assign_types(3) == ["choice", "choice", "choice"]


def test_card_language_boundaries():
    from services import language
    assert language.is_english_card({"front": "Portfolio governance", "back": "Select investments"})
    assert not language.is_english_card({"front": "组合治理", "back": "选择投资"})
    assert not language.is_english_card({"front": "Portfolio 治理", "back": "混合 中文"})
    assert quizgen.bool_options({"front": "Portfolio governance", "back": "Select investments"}) == ["True", "False"]
    assert quizgen.bool_options({"front": "组合治理", "back": "选择投资"}) == ["对", "错"]


def test_english_bool_validation_requires_exact_labels():
    item = {"type": "bool", "stem": "Is this true?", "options": ["True", "False"], "answer_key": "True"}
    assert quizgen._validate(item, "bool", ["True", "False"])["answer_key"] == "True"
    assert quizgen._validate({**item, "options": ["对", "错"], "answer_key": "对"}, "bool", ["True", "False"]) is None


def test_reswap_uses_canonical_content_hash_source():
    src = (BACKEND / "scripts" / "reswap_card_text.py").read_text(encoding="utf8")
    store = (BACKEND / "scripts" / "ingest_store.py").read_text(encoding="utf8")
    assert "from scripts.ingest_store import _owner_id, content_hash" in src
    assert src.count("def content_hash") == 0
    assert store.count("def content_hash") == 1


# —— QUIZ-011：卡文语种 = 题面语种 + 卡文变化 → 同 id 覆盖重生 ——

def _seed_one_card(tmp_path, *, front, back, hash_=None):
    """最小库：1 科 1 书 1 章 1 概念 1 卡（content_hash 与卡文同源）。"""
    from scripts import ingest_store
    con = ingest_store.connect(str(tmp_path / "seed.sqlite3"))
    con.execute("INSERT INTO subjects(id,name,slug,order_no,created_at) VALUES(1,'psy','demo',0,'t')")
    con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,1,1,'b','book','active','t')")
    con.execute("INSERT INTO chapters(id,book_id,name,order_no,anchor,status,unlocked_at) VALUES(1,1,'ch',1,'ch','unlocked','t')")
    con.execute("INSERT INTO concepts(id,concept_uid,chapter_id,name) VALUES(1,'c1',1,'c1')")
    con.execute("INSERT INTO cards(id,concept_id,subject_id,front,back,source,content_hash,status,learn_count,created_at)"
                " VALUES(1,1,1,?,?,'s',?,'reviewing',1,'t')",
                (front, back, hash_ or ingest_store.content_hash(front, back)))
    con.commit()
    return con


def test_mechanical_bool_english_stem_has_no_cjk():
    class _Con:
        def execute(self, *a, **k):
            raise AssertionError("bool 派生不应查同章池")
    item = quizgen.mechanical_item(_Con(), {"card_id": 1, "front": "Portfolio governance",
                                            "back": "Select investments", "chapter_id": 9}, "bool")
    assert item["type"] == "bool" and item["options"] == ["True", "False"]
    assert "判断" not in item["stem"] and "Select investments" in item["stem"]
    assert not any("一" <= ch <= "鿿" for ch in item["stem"])   # 英文卡题面不得含汉字


def test_cached_item_rejects_stale_card_hash(tmp_path):
    """QUIZ-011：card_content_hash 与卡当前 content_hash 不一致的缓存题不算命中。"""
    con = _seed_one_card(tmp_path, front="Portfolio governance", back="Select investments")
    item = quizgen.insert_item(con, 1, {"type": "bool", "stem": "True or False: Select investments",
                                        "options": ["True", "False"], "answer_key": "True",
                                        "source": "fallback"})
    con.commit()
    assert quizgen.cached_item(con, 1)["id"] == item["id"]          # 卡文未变 → 命中
    # 卡文变化：content_hash 换新，但旧题仍记着旧指纹 → 不再命中
    new_hash = "stale-hash-for-changed-card"
    con.execute("UPDATE cards SET content_hash=?", (new_hash,))
    con.commit()
    assert quizgen.cached_item(con, 1) is None


def test_card_text_change_regenerates_in_place_preserving_attempts(tmp_path, monkeypatch):
    """QUIZ-011：卡文变化 → 同 id 覆盖重生（不删不插），quiz_attempts 行数与关联不变。"""
    monkeypatch.setattr(quizgen, "_chat", lambda _m: None)          # 纯机械，不触网
    con = _seed_one_card(tmp_path, front="Portfolio governance",
                         back="Old point\nSecond point")
    card = {"card_id": 1, "front": "Portfolio governance", "back": "Old point\nSecond point",
            "chapter_id": 1}
    first = quizgen.ensure_items(con, [card])[0]
    con.execute("INSERT INTO quiz_attempts(user_id,item_id,card_id,session_id,my_answer,is_correct,created_at) VALUES(1,?,1,'s1','x',0,'2026-09-27T00:00:00+00:00')", (first["id"],))
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM quiz_items").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM quiz_attempts").fetchone()[0] == 1

    con.execute("UPDATE cards SET front=?, back=?, content_hash=? WHERE id=1",
                ("Portfolio governance", "New point\nSecond point",
                 __import__("scripts.ingest_store", fromlist=["content_hash"])
                 .content_hash("Portfolio governance", "New point\nSecond point")))
    con.commit()
    second = quizgen.ensure_items(con, [{"card_id": 1, "front": "Portfolio governance",
                                         "back": "New point\nSecond point", "chapter_id": 1}])[0]
    assert second["id"] == first["id"], "卡文变化必须同 id 覆盖重生（QUIZ-011，不删不插）"
    assert second["stem"] != first["stem"]
    assert "New point" in second["stem"] and "Old point" not in second["stem"]
    assert con.execute("SELECT COUNT(*) FROM quiz_items").fetchone()[0] == 1   # 仍一行
    assert con.execute("SELECT COUNT(*) FROM quiz_attempts").fetchone()[0] == 1  # 作答不受影响
    assert con.execute("SELECT item_id FROM quiz_attempts").fetchone()[0] == first["id"]


# —— QUIZ-012：题型必须逐字兑现 + 干扰项不得取纯名词标签（2026-10-03 生产缺陷回归） ——

LABELS = ("了解（knowledge）\n关心（care）\n相互依赖性（interdependence）\n"
          "相互一致性（mutuality）\n信任（trust）\n承诺（commitment）")
CLAIMS = ["伴侣之间在六个方面存在程度差异，未必全部出现。", "只有部分特征时，亲密程度就会减弱。",
          "归属需要使人寻求持续而稳定的关爱与包容关系。", "缺乏归属会带来孤独与痛苦。",
          "同居时间越长，对婚姻的热情越低。", "低自尊者会低估伴侣的爱。"]


def _seed_chapter(tmp_path, backs: list[str], name="quiz012.sqlite3"):
    """1 科 1 书 1 章 N 概念 N 卡（每卡一概念，back 用换行分要点）。"""
    from scripts import ingest_store
    con = ingest_store.connect(str(tmp_path / name))
    con.execute("INSERT INTO subjects(id,name,slug,order_no,created_at) VALUES(1,'psy','demo',0,'t')")
    con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,1,1,'b','book','active','t')")
    con.execute("INSERT INTO chapters(id,book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,1,'ch',1,'ch','unlocked','t')")
    cards = []
    for i, back in enumerate(backs, start=1):
        con.execute("INSERT INTO concepts(id,concept_uid,chapter_id,name) VALUES(?,?,1,?)",
                    (i, f"c{i}", f"概念{i}"))
        front = f"概念{i}的要点是什么？"
        con.execute("INSERT INTO cards(id,concept_id,subject_id,front,back,source,content_hash,status,"
                    "learn_count,created_at) VALUES(?,?,1,?,?,'s',?,'reviewing',1,'t')",
                    (i, i, front, back, ingest_store.content_hash(front, back)))
        cards.append({"card_id": i, "front": front, "back": back, "chapter_id": 1})
    con.commit()
    return con, cards


def test_prompt_skeleton_follows_wanted_types():
    """回归（QUIZ-012）：骨架必须按 want 生成。

    旧版骨架写死 `{"type":"bool",…}` 且规则只讲判断题 → 模型照抄样例，要选择题也返 bool，
    被 `_validate` 拒收 → 生产里 2026-09-27 起 28 道选择题**全部**降级为机械题。
    """
    cards = [{"card_id": 1, "front": "合成示例书10包括哪些要点？", "back": LABELS, "chapter_id": 1},
             {"card_id": 2, "front": "归属需要指什么？", "back": CLAIMS[2], "chapter_id": 1}]
    only_choice = quizgen._system_prompt(cards[:1], ["choice"])
    assert '"type": "choice"' in only_choice
    assert '"type": "bool"' not in only_choice, "要选择题时骨架不得出现是非题样例"
    assert "必须逐字照办" in only_choice

    mixed = quizgen._system_prompt(cards, ["choice", "bool"])
    assert '"type": "choice"' in mixed and '"type": "bool"' in mixed
    assert '"want": "choice"' in mixed and '"want": "bool"' in mixed


def test_llm_batch_rejects_wrong_type_and_warns(monkeypatch, caplog):
    """回归（QUIZ-012）：要选择题却返是非题 → 一律作废 + 记 warning（可观测性）。"""
    card = {"card_id": 7, "front": "合成示例书10包括哪些要点？", "back": LABELS, "chapter_id": 1}
    monkeypatch.setattr(quizgen, "_chat", lambda _m: json.dumps(
        {"items": [{"card_id": 7, "type": "bool", "stem": "判断：…", "options": ["对", "错"],
                    "answer_key": "对"}]}, ensure_ascii=False))
    with caplog.at_level(logging.WARNING):
        assert quizgen.llm_batch([card], ["choice"]) == {}
    assert any("题型不符" in r.getMessage() for r in caplog.records)


def test_gloss_label_boundaries():
    assert quizgen.is_gloss_label("了解（knowledge）") is True
    assert quizgen.is_gloss_label("相互依赖性（interdependence）") is True
    assert quizgen.is_gloss_label("care (care)") is True
    assert quizgen.is_gloss_label("需要时能返回并获得安抚") is False
    assert quizgen.is_gloss_label("了解（knowledge）：知道伴侣的喜好与厌恶") is False
    assert quizgen.is_gloss_label("低自尊者会低估伴侣的爱。") is False


def test_mechanical_choice_never_uses_gloss_label_distractors(tmp_path):
    """卡 194 现场：同章第一张卡的要点全是「X（english）」标签 → 不得被选作干扰项。"""
    con, cards = _seed_chapter(tmp_path, [LABELS] + CLAIMS)
    item = quizgen.mechanical_item(con, cards[1], "choice")
    assert item["type"] == "choice"
    for o in item["options"]:
        assert not quizgen.is_gloss_label(o), f"纯名词标签不得进选项：{o}"
        assert len(o) >= quizgen.DISTRACTOR_MIN_CHARS
    assert item["answer_key"] == CLAIMS[0]


def test_mechanical_choice_distractors_vary_between_cards(tmp_path):
    """旧实现 `pool[:2]` → 同章每道题干扰项完全相同（用户截图：了解 / 关心）。"""
    con, cards = _seed_chapter(tmp_path, [LABELS] + CLAIMS)
    pairs = []
    for c in cards[1:]:
        it = quizgen.mechanical_item(con, c, "choice")
        assert it["type"] == "choice"
        pairs.append(frozenset(set(it["options"]) - {it["answer_key"]}))
    assert len(set(pairs)) > 1, "同章不同卡的干扰项不得恒等（QUIZ-012）"
    # 确定性：同库同卡 → 结果逐字相同（幂等，缓存可复用）
    again = quizgen.mechanical_item(con, cards[1], "choice")
    assert sorted(again["options"]) == sorted(quizgen.mechanical_item(con, cards[1], "choice")["options"])


def test_mechanical_degrades_to_bool_when_correct_is_label(tmp_path):
    """正确答案本身是纯标签 → 不生造烂选择题，降级为是非题（QUIZ-003 允许的退化）。"""
    con, cards = _seed_chapter(tmp_path, [LABELS] + CLAIMS, name="quiz012b.sqlite3")
    item = quizgen.mechanical_item(con, cards[0], "choice")
    assert item["type"] == "bool" and item["options"] == ["对", "错"]
