"""M2-B1 客观题管道：QUIZ-001…006 + WRONG-001 —— 逐条对 REQ 断言（口径可证伪）。

- LLM 一律 **mock**（`quizgen._chat`）：不触网。降级路径显式 mock 返错/返空。
- 反向断言：会话响应零 `answer_key` 泄漏；判分模块零网络/LLM 客户端；重复作答追加不覆盖。
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402

from scripts import ingest_kb  # noqa: E402
from services import quiz, quizgen  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cards-contract-1.jsonl"


def _fake_llm(messages):
    """按 prompt 里的考点上下文，返回一份合法 JSON 题集（模拟 DeepSeek 正常返回）。"""
    ctx = json.loads(messages[0]["content"].split("考点：\n", 1)[1])
    items = []
    for c in ctx:
        pts = c["answer_points"] or [c["question"]]
        if c["want"] == "bool":
            items.append({"card_id": c["card_id"], "type": "bool",
                          "stem": f"判断：{pts[0]}", "options": ["对", "错"], "answer_key": "对"})
        else:
            items.append({"card_id": c["card_id"], "type": "choice", "stem": c["question"],
                          "options": pts[:4], "answer_key": pts[0]})
    return json.dumps({"items": items}, ensure_ascii=False)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """正常路径：LLM 正常返回。"""
    monkeypatch.setattr(quizgen, "_chat", _fake_llm)
    db = tmp_path / "quiz.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    ingest_kb.ingest_file(con, FIXTURE)
    con.execute("UPDATE cards SET status=\'reviewing\', next_review_at=\'2020-01-01T00:00:00+08:00\'")
    con.commit()
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _seed_locked_only(db):
    """第 1 章解锁但 0 张卡；第 2 章锁定但有 3 张卡 → 两组队列都应为空。"""
    con = ingest_kb.connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('psy','demo',0,'t')")
    con.execute("INSERT INTO books(subject_id,title,slug,status,created_at,owner_id) VALUES(1,'书','book','active','t',1)")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,'第1章',1,'第1章','unlocked','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,'第2章',2,'第2章','unlocked',NULL)")
    cid = con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('b',2,'概念B')").lastrowid
    for i in range(3):
        con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                    "learn_count,next_review_at,created_at) VALUES(?,1,?,?,'s',?,'new',0,NULL,'t')",
                    (cid, f"锁定题{i}", f"答案{i}", f"h{i}"))
    con.commit()
    con.close()


@pytest.fixture()
def locked_client(tmp_path, monkeypatch):
    monkeypatch.setattr(quizgen, "_chat", _fake_llm)
    db = tmp_path / "locked.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    _seed_locked_only(db)
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _start(client, size=10, **kw):
    body = {"size": size}
    body.update(kw)
    r = client.post("/api/quiz/session", json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def _answer(client, sid, item_id, value):
    r = client.post("/api/quiz/answer",
                    json={"session_id": sid, "item_id": item_id, "my_answer": value})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def _db(client):
    from data.db import get_db
    return get_db()


def _correct(client, item):
    """该题的**正确选项文本**（QUIZ-014）。

    服务端既不下发 `answer_key`、也不把正确答案固定在某个位置，所以测试必须从库里取；
    **禁止**再假设「第一个选项就是正确答案」——那正是本 bug 的白纸黑字（会变成随机通过）。
    """
    with client.application.app_context():
        row = _db(client).execute(
            "SELECT answer_key FROM quiz_items WHERE id=?", (item["id"],)).fetchone()
    assert row["answer_key"] in item["options"], "正确答案必须逐字出现在下发选项里"
    return row["answer_key"]


# —— QUIZ-001 题型 + 零答案泄漏 ——
def test_session_types_and_no_answer_key_leak(client):
    d = _start(client)
    assert d["size"] == 2 and len(d["items"]) == 2      # 第 1 章 2 张；第 2 章锁定被排除
    for it in d["items"]:
        assert it["type"] in ("choice", "bool")
        assert len(it["options"]) >= 2
        assert it["stem"].strip()
        assert set(it) <= {"id", "card_id", "type", "stem", "options", "book", "chapter", "source_label"}
        for leaked in ("answer_key", "answer", "source", "points"):
            assert leaked not in it
    # 反向断言（QUIZ-001）：整个响应体里出现 answer_key 即失败
    assert "answer_key" not in json.dumps(d, ensure_ascii=False)


def test_db_items_have_answer_key_and_type(client):
    _start(client)
    with client.application.app_context():
        rows = _db(client).execute("SELECT type, answer_key, options, source FROM quiz_items").fetchall()
    assert rows
    for r in rows:
        assert r["type"] in ("choice", "bool")
        assert r["answer_key"].strip()
        assert len(json.loads(r["options"])) >= 2


# —— QUIZ-002 缓存 / 幂等 / 会话内不重复 ——
def test_session_card_ids_unique(client):
    d = _start(client, size=50)
    ids = [it["card_id"] for it in d["items"]]
    assert ids and len(ids) == len(set(ids))


def test_second_run_adds_zero_items_and_calls_no_llm(client, monkeypatch):
    calls = {"n": 0}

    def counting(messages):
        calls["n"] += 1
        return _fake_llm(messages)

    monkeypatch.setattr(quizgen, "_chat", counting)
    _start(client)
    with client.application.app_context():
        first = _db(client).execute("SELECT COUNT(*) FROM quiz_items").fetchone()[0]
    d2 = _start(client)
    with client.application.app_context():
        second = _db(client).execute("SELECT COUNT(*) FROM quiz_items").fetchone()[0]
    assert d2["size"] == 2
    assert first == second, "同输入连跑两次，第二次 quiz_items 必须新增 0（幂等，QUIZ-002）"
    assert calls["n"] == 1, "第二次全部命中缓存，绝不得再直连 LLM"


def test_cached_item_prefers_unanswered(client):
    d = _start(client)
    item = d["items"][0]
    _answer(client, d["session_id"], item["id"], item["options"][0])   # 该题已作答
    with client.application.app_context():
        con = _db(client)
        card_hash = con.execute("SELECT content_hash FROM cards WHERE id=?",
                                (item["card_id"],)).fetchone()[0]
        con.execute("INSERT INTO quiz_items(card_id,type,stem,options,answer_key,points,source,"
                    "content_hash,card_content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (item["card_id"], "bool", "判断：新题", '["对","错"]', "对", 1, "fallback",
                     quizgen.content_hash(item["card_id"], "bool", "判断：新题"), card_hash, "t"))
        con.commit()
        picked = quizgen.cached_item(con, item["card_id"], user_id=1)
    # 优先未作答过的缓存题（QUIZ-002 ③：缓存足够时不得重复出已答过的题）
    assert picked["stem"] == "判断：新题"


def test_cross_session_reuses_cache_without_llm(client, monkeypatch):
    calls = {"n": 0}

    def counting(messages):
        calls["n"] += 1
        return _fake_llm(messages)

    monkeypatch.setattr(quizgen, "_chat", counting)
    _start(client)
    _start(client)
    _start(client)
    assert calls["n"] == 1


# —— QUIZ-003 降级 ——
@pytest.mark.parametrize("bad", [None, "", "这不是 JSON", '{"items": []}'])
def test_fallback_when_llm_fails(tmp_path, monkeypatch, caplog, bad):
    monkeypatch.setattr(quizgen, "_chat", lambda _m, _bad=bad: _bad)
    db = tmp_path / "fb.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    ingest_kb.ingest_file(con, FIXTURE)
    con.execute("UPDATE cards SET status='reviewing', next_review_at='2020-01-01T00:00:00+08:00'")
    con.execute("UPDATE chapters SET unlocked_at='2026-09-27T00:00:00+08:00', status='unlocked'")
    con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('fallback-extra',1,'额外')")
    extra = con.execute("SELECT id FROM concepts WHERE concept_uid='fallback-extra'").fetchone()[0]
    con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,created_at) VALUES(?,1,'额外题','干扰项A\n干扰项B','s','fallback-extra','reviewing','t')", (extra,))
    con.execute("UPDATE cards SET back='答案A\n答案B' WHERE concept_id=? AND id<>?", (extra, -1))
    con.commit()
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c, caplog.at_level(logging.WARNING, logger="services.quizgen"):
        d = _start(c)
        assert d["size"] >= 1, "LLM 失败也必须保证有题（QUIZ-003）"
        with app.app_context():
            rows = _db(c).execute("SELECT source, answer_key FROM quiz_items").fetchall()
        assert rows and all(r["source"] == "fallback" for r in rows)
        assert all(r["answer_key"].strip() for r in rows)
    assert any("fallback" in rec.message for rec in caplog.records), "降级必记 logging.warning"


def test_fallback_choice_distractors_from_same_chapter(tmp_path, monkeypatch):
    """QUIZ-003：LLM 降级出的 choice，正确项来自本卡、干扰项来自**同章其他卡**答案要点。"""
    monkeypatch.setattr(quizgen, "_chat", lambda _m: None)
    db = tmp_path / "fb2.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    ingest_kb.ingest_file(con, FIXTURE)
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        _start(c)
        with app.app_context():
            con = _db(c)
            rows = con.execute("SELECT card_id, type, options, answer_key FROM quiz_items").fetchall()
            for r in rows:
                own = [p for p in con.execute("SELECT back FROM cards WHERE id=?", (r["card_id"],))
                       .fetchone()["back"].split("\n") if p.strip()]
                others = []
                for o in con.execute(
                        "SELECT c.back FROM cards c JOIN concepts cp ON cp.id=c.concept_id"
                        " WHERE cp.chapter_id=(SELECT cp2.chapter_id FROM cards c2"
                        "   JOIN concepts cp2 ON cp2.id=c2.concept_id WHERE c2.id=?) AND c.id<>?",
                        (r["card_id"], r["card_id"])).fetchall():
                    others += [p for p in o["back"].split("\n") if p.strip()]
                opts = json.loads(r["options"])
                assert r["answer_key"] in opts
                assert r["answer_key"] in own                       # 正确项来自本卡
                distractors = [o for o in opts if o != r["answer_key"]]
                assert distractors and set(distractors) <= set(others), "干扰项必须来自同章其他卡"
                assert set(opts) <= set(own) | set(others)          # 全部回溯库内文本


# —— 出题器单元 ——
def test_assign_types_ratio_default_7_3():
    types = quizgen.assign_types(10)
    assert types.count("choice") == 7 and types.count("bool") == 3


def test_mechanical_bool_item_shape():
    class _Con:  # 纯机械 bool 不查库
        def execute(self, *a, **k):
            raise AssertionError("bool 派生不应查同章池")
    item = quizgen.mechanical_item(_Con(), {"card_id": 1, "front": "题", "back": "要点甲",
                                            "chapter_id": 9}, "bool")
    assert item["type"] == "bool"
    assert item["options"] == ["对", "错"] and item["answer_key"] == "对"
    assert "要点甲" in item["stem"] and item["source"] == "fallback"


def test_parse_json_tolerates_fences():
    assert quizgen._parse_json('```json\n{"items": []}\n```') == {"items": []}
    assert quizgen._parse_json("前缀 {\"a\": 1} 后缀") == {"a": 1}
    assert quizgen._parse_json("没有 json") is None


# —— QUIZ-004 确定性判分 ——
def test_grade_exact_match_only():
    assert quiz.grade("对", "对") is True
    assert quiz.grade("对 ", "对") is False      # 前后空白 → 仍判错（口径：不规范化）
    assert quiz.grade("安全型", "安全型：能亲近也能独立") is False
    assert quiz.grade("A", "a") is False


def test_grading_module_has_no_network_client():
    """反向断言（QUIZ-004）：判分模块不得引入网络/LLM 客户端。"""
    src = (BACKEND / "services" / "quiz.py").read_text(encoding="utf-8")
    for token in ("requests", "httpx", "openai"):
        assert token not in src, f"判分路径不得出现 {token}"


def test_wrong_answer_graded_zero_and_correct_one(client):
    d = _start(client)
    it = d["items"][0]
    good = _answer(client, d["session_id"], it["id"], _correct(client, it))
    assert good["is_correct"] is True and good["correct_answer"] == _correct(client, it)
    it2 = d["items"][1]
    bad = _answer(client, d["session_id"], it2["id"], "__乱答__")
    assert bad["is_correct"] is False
    assert bad["correct_answer"] in it2["options"]


# —— QUIZ-005 得分口径 ——
def test_score_formula_with_correct_wrong_unanswered(client):
    d = _start(client, size=2)
    it, it2 = d["items"][0], d["items"][1]
    _answer(client, d["session_id"], it["id"], _correct(client, it))       # 对
    # it2 不作答（未答不入分母）
    res = client.get(f"/api/quiz/session/{d['session_id']}/result").get_json()["data"]
    assert res["answered"] == 1 and res["correct"] == 1 and res["score"] == 100

    _answer(client, d["session_id"], it2["id"], "__错__")               # 错
    res = client.get(f"/api/quiz/session/{d['session_id']}/result").get_json()["data"]
    assert res["answered"] == 2 and res["correct"] == 1 and res["score"] == 50


def test_score_zero_when_no_answers(client):
    d = _start(client)
    res = client.get(f"/api/quiz/session/{d['session_id']}/result").get_json()["data"]
    assert {k: res[k] for k in ("answered", "correct", "score", "wrong")} == {"answered": 0, "correct": 0, "score": 0, "wrong": []}
    assert res["items"] == []   # 零作答仍返回空解析项


def test_score_rounding(client):
    """x/y 取整：答对 1 / 已答 3 → 33。"""
    d = _start(client, size=2)
    it0, it1 = d["items"][0], d["items"][1]
    sid = d["session_id"]
    with client.application.app_context():
        con = _db(client)
        extra = con.execute(
            "INSERT INTO quiz_items(card_id,type,stem,options,answer_key,points,source,content_hash,"
            "created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (it1["card_id"], "bool", "判断：额外题", '["对","错"]', "对", 1, "fallback",
             quizgen.content_hash(it1["card_id"], "bool", "判断：额外题"), "t")).lastrowid
        con.execute("INSERT INTO quiz_attempts(item_id,card_id,session_id,my_answer,is_correct,"
                    "created_at,user_id) VALUES(?,?,?,?,1,'2026-01-01T00:00:00+00:00',1)",
                    (extra, it1["card_id"], sid, "对"))       # 会话内已答对 1 题
        con.commit()
    _answer(client, sid, it0["id"], "__错__")
    _answer(client, sid, it1["id"], "__错__")
    res = client.get(f"/api/quiz/session/{sid}/result").get_json()["data"]
    assert res["answered"] == 3 and res["correct"] == 1
    assert res["score"] == 33, "round(1/3*100) = 33"


# —— QUIZ-006 追加不覆盖 + UTC ——
def test_repeat_answer_appends_rows_not_overwrite(client):
    d = _start(client)
    it = d["items"][0]
    for v in (_correct(client, it), "__错__", _correct(client, it)):
        _answer(client, d["session_id"], it["id"], v)
    with client.application.app_context():
        rows = _db(client).execute(
            "SELECT my_answer, is_correct, created_at FROM quiz_attempts WHERE item_id=? ORDER BY id",
            (it["id"],)).fetchall()
    assert len(rows) == 3, "重复作答必须追加不覆盖（QUIZ-006）"
    assert [r["is_correct"] for r in rows] == [1, 0, 1]
    for r in rows:
        assert r["created_at"].endswith("+00:00"), r["created_at"]
        datetime.fromisoformat(r["created_at"])   # 合法 ISO 8601


def test_review_schedule_reused(client):
    d = _start(client)
    it = d["items"][0]
    body = _answer(client, d["session_id"], it["id"], _correct(client, it))
    assert body["card"]["learn_count"] == 1 and body["card"]["status"] == "reviewing"  # 复用唯一一套调度


# —— WRONG-001 错题本 ——
def _wrong_of(client, card_id):
    items = client.get("/api/wrong").get_json()["data"]["items"]
    return next((x for x in items if x["card_id"] == card_id), None)


def test_wrong_book_sorted_desc_and_expandable(client):
    d = _start(client, size=2)
    a, b = d["items"][0], d["items"][1]
    for _ in range(3):
        _answer(client, d["session_id"], a["id"], "__错__")
    _answer(client, d["session_id"], b["id"], "__错__")
    items = client.get("/api/wrong").get_json()["data"]["items"]
    assert [x["wrong_count"] for x in items] == [3, 1]          # 按错次降序
    assert items[0]["card_id"] == a["card_id"]
    for x in items:                                             # 可展开对照两字段
        assert x["correct_answer"].strip() and x["my_answer"] == "__错__"
        assert x["stem"].strip()


def test_wrong_book_ignores_correct_attempts(client):
    d = _start(client)
    it = d["items"][0]
    _answer(client, d["session_id"], it["id"], _correct(client, it))     # 只对了一次
    assert client.get("/api/wrong").get_json()["data"]["items"] == []


def test_wrong_retry_appends_and_updates_count(client):
    d = _start(client, size=1)
    a = d["items"][0]
    _answer(client, d["session_id"], a["id"], "__错__")
    assert _wrong_of(client, a["card_id"])["wrong_count"] == 1
    retry = client.post("/api/wrong/retry", json={"card_id": a["card_id"]}).get_json()["data"]
    assert retry["size"] == 1
    assert retry["items"][0]["card_id"] == a["card_id"]
    assert "answer_key" not in json.dumps(retry, ensure_ascii=False)
    _answer(client, retry["session_id"], retry["items"][0]["id"], "__又错__")
    assert _wrong_of(client, a["card_id"])["wrong_count"] == 2      # 重刷后计数更新


# —— 旧端点保留 + 边界 ——
def test_legacy_reveal_still_available(client):
    d = _start(client)
    cid = d["items"][0]["card_id"]
    r = client.get(f"/api/quiz/session/{d['session_id']}/answer/{cid}")
    assert r.status_code == 200
    assert r.get_json()["data"]["answer_points"]


def test_progress_endpoint(client):
    d = _start(client)
    it = d["items"][0]
    _answer(client, d["session_id"], it["id"], _correct(client, it))
    st = client.get(f"/api/quiz/session/{d['session_id']}").get_json()["data"]
    assert st["total"] == 2 and st["answered"] == 1 and st["correct"] == 1 and st["score"] == 100


def test_locked_chapter_excluded(locked_client):
    today = locked_client.get("/api/today").get_json()["data"]
    assert today["due"] == [] and today["new"] == []
    d = _start(locked_client)
    assert d["size"] == 0 and d["items"] == []


def test_subject_filter(client):
    assert _start(client, subject="demo")["size"] == 2


def test_session_size_capped(client):
    assert _start(client, size=10 ** 6)["size"] == 2       # 队列只有 2 张


def test_errors(client):
    d = _start(client)
    it = d["items"][0]
    assert client.post("/api/quiz/answer", json={"session_id": "nope", "item_id": it["id"],
                                                 "my_answer": "x"}).status_code == 404
    assert client.post("/api/quiz/answer", json={"session_id": d["session_id"], "item_id": 999,
                                                 "my_answer": "x"}).status_code == 400
    assert client.post("/api/quiz/answer", json={"session_id": d["session_id"], "item_id": it["id"],
                                                 "my_answer": "  "}).status_code == 400
    assert client.post("/api/quiz/answer", json={"session_id": d["session_id"], "item_id": "abc",
                                                 "my_answer": "x"}).status_code == 400
    assert client.post("/api/quiz/answer", json={"item_id": it["id"], "my_answer": "x"}).status_code == 400
    assert client.get("/api/quiz/session/deadbeef").status_code == 404
    assert client.get("/api/quiz/session/deadbeef/result").status_code == 404
    assert client.get(f"/api/quiz/session/{d['session_id']}/answer/999").status_code == 404
    assert client.post("/api/quiz/session", json={"subject": "nope"}).status_code == 404
    assert client.post("/api/quiz/session", json={"size": 0}).status_code == 400
    assert client.post("/api/wrong/retry", json={}).status_code == 400
    assert client.post("/api/wrong/retry", json={"card_id": "x"}).status_code == 400
    assert client.post("/api/wrong/retry", json={"card_id": 999999}).status_code == 404


def test_result_maps_to_single_scheduler():
    """判对/判错复核到唯一一套调度档位（QUIZ-006 → REVIEW-001）。"""
    assert quiz._RESULT_MAP[True] == "good" and quiz._RESULT_MAP[False] == "again"


def test_duplicate_card_in_queue_is_deduped(client, monkeypatch):
    """会话内 card_id 不重复的构造保证：即使队列给出重复行也只出一题（QUIZ-002）。"""
    with client.application.app_context():
        row = _db(client).execute(
            "SELECT c.id AS card_id, c.front, c.back, cp.chapter_id"
            " FROM cards c JOIN concepts cp ON cp.id=c.concept_id LIMIT 1").fetchone()
    card = dict(row)
    monkeypatch.setattr("services.quiz._quiz_pool", lambda con, subject_id=None, book_ids=None, user_id=None: [card, dict(card)])
    monkeypatch.setattr(quizgen, "ensure_items", lambda con, cards, user_id=None: [
        {"id": 1, "card_id": cards[0]["card_id"], "type": "bool", "stem": "Q", "options": ["对", "错"]}
    ])
    with client.application.app_context():
        d = quiz.start_session(_db(client), size=10)
    assert d["size"] == 1 and len(d["items"]) == 1


def test_reveal_missing_card_returns_404(client):
    """旧端点保留，但卡被删后应 404（不 500，也不编造答案）。"""
    d = _start(client)
    card_id = d["items"][0]["card_id"]
    with client.application.app_context():
        con = _db(client)
        con.execute("DELETE FROM cards WHERE id=?", (card_id,))
        con.commit()
    assert client.get(f"/api/quiz/session/{d['session_id']}/answer/{card_id}").status_code == 404


def test_round10_display_exits(client):
    from services import labels
    from data.db import get_db
    session = _start(client)
    it = session['items'][0]
    with client.application.app_context():
        ctx = quizgen.card_context(get_db(), it['card_id'], user_id=1)
        assert it['source_label'] == labels.display_fields(ctx)['source_label']
    assert 'answer_points' not in it
    client.post('/api/quiz/answer', json={'session_id': session['session_id'],
                'item_id': it['id'], 'my_answer': 'intentionally wrong'})
    result = client.get(f"/api/quiz/session/{session['session_id']}/result").json['data']
    wrong = client.get('/api/wrong').json['data']['items']
    weak = client.get('/api/weak').json['data']['chapters']
    reveal = client.get(f"/api/quiz/session/{session['session_id']}/answer/{it['card_id']}").json['data']
    with client.application.app_context():
        expected = labels.display_fields(quizgen.card_context(get_db(), it['card_id'], user_id=1))
        for row in (result['items'][0], wrong[0], weak[0]['cards'][0]):
            assert row['source_label'] == expected['source_label']
            assert row['answer_points'] == expected['answer_points']
        assert reveal['answer_points'] == expected['answer_points']
