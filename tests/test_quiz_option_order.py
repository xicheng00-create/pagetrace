"""QUIZ-014：选项**呈现顺序**不得固定（2026-10-13 owner 报障「答案恒在 A」）。

断言三层：
- **正向**：同一题跨会话重新置换 → 位置近似均匀（不再恒首位）；
- **一致**：结果页逐题解析的顺序 == 作答时下发顺序（同一会话恒定）；
- **反向**：`answer_key` 始终不下发；判分仍按**文本**比对（QUIZ-004）。

故障形态复现：本文件 mock 的 LLM 把正确项**恒排首位**（旧提示词骨架正是这么教的），
若呈现层没打乱，`test_served_answer_position_is_not_always_first` 必然失败（可反证）。
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402
from services import quizgen, quiztext  # noqa: E402

from scripts import ingest_kb  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cards-contract-1.jsonl"

POSITIONS = "ABCD"


def _biased_llm(messages):
    """正确项**恒排首位**的 LLM（复现报障形态：模型照抄旧骨架的位置）。"""
    ctx = json.loads(messages[0]["content"].split("考点：\n", 1)[1])
    items = []
    for c in ctx:
        pts = c["answer_points"] or [c["question"]]
        if c["want"] == "bool":
            items.append({"card_id": c["card_id"], "type": "bool", "stem": f"判断：{pts[0]}",
                          "options": ["对", "错"], "answer_key": "对"})
        else:
            correct = pts[0]
            items.append({
                "card_id": c["card_id"], "type": "choice", "stem": c["question"],
                "options": [correct, f"干扰项甲：{correct}这一说法并不成立",
                            f"干扰项乙：{correct}这一说法并不成立"],
                "answer_key": correct,
            })
    return json.dumps({"items": items}, ensure_ascii=False)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(quizgen, "_chat", _biased_llm)
    db = tmp_path / "order.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    ingest_kb.ingest_file(con, FIXTURE)
    con.execute("UPDATE cards SET status='reviewing', next_review_at='2020-01-01T00:00:00+08:00'")
    con.commit()
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _session(client, **body):
    r = client.post("/api/quiz/session", json=body)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["data"]


def _answer_key_of(client, item_id) -> str:
    """测试内直读库：拿到该题的真实答案（服务端不下发 answer_key）。"""
    from data.db import get_db
    with client.application.app_context():
        row = get_db().execute("SELECT answer_key FROM quiz_items WHERE id=?", (item_id,)).fetchone()
    return row["answer_key"]


# —— 正向：位置均匀 ——
def test_display_options_positions_are_uniform_in_bulk():
    """300 题、正确答案一律在首位 → 置换后三个位置都出现、无位置独占。"""
    options = ["正确答案（完整说法）", "干扰甲（完整说法）", "干扰乙（完整说法）"]
    seen = Counter()
    for i in range(300):
        served = quiztext.display_options(options, ctx=f"s{i}", item_id=i)
        assert sorted(served) == sorted(options), "置换不得增删选项"
        seen[served.index(options[0])] += 1
    assert set(seen) == {0, 1, 2}, f"位置覆盖不全: {dict(seen)}"
    assert max(seen.values()) / 300 <= 0.45, f"某位置独占: {dict(seen)}"


def test_display_options_deterministic_per_ctx_and_reshuffled_across_ctx():
    """同一会话同一题恒定（结果页要复现）；换会话重排。"""
    options = ["甲（完整说法）", "乙（完整说法）", "丙（完整说法）"]
    same = [quiztext.display_options(options, ctx="sess-a", item_id=7) for _ in range(5)]
    assert len({tuple(s) for s in same}) == 1, "同一会话内顺序必须恒定"
    variants = {tuple(quiztext.display_options(options, ctx=f"sess-{i}", item_id=7)) for i in range(40)}
    assert len(variants) >= 2, "跨会话必须重新置换"
    # <2 项的退化输入原样返回
    assert quiztext.display_options(["唯一（完整说法）"], ctx="s", item_id=1) == ["唯一（完整说法）"]
    assert quiztext.display_options([], ctx="s", item_id=1) == []


# —— 集成：报障形态被纠正 ——
def test_served_answer_position_is_not_always_first(client):
    """4 题 × 12 个会话：库里答案 100% 在首位，下发给前端的顺序必须散开。"""
    seen = Counter()
    per_item = {}
    for i in range(12):
        data = _session(client)
        assert data["items"], "会话必须出题"
        for it in data["items"]:
            key = _answer_key_of(client, it["id"])
            assert key in it["options"], "正确项必须在选项里"
            pos = it["options"].index(key)
            seen[pos] += 1
            per_item.setdefault(it["id"], set()).add(pos)
    # 库里位置（故障形态）：全部 index 0
    assert all(0 in p for p in per_item.values())
    assert set(seen) == {0, 1, 2}, f"呈现位置覆盖不全: {dict(seen)}"
    assert max(seen.values()) / sum(seen.values()) <= 0.6, f"某位置独占: {dict(seen)}"
    assert any(len(p) >= 2 for p in per_item.values()), "同一题跨会话必须换位置"


def test_answer_key_never_downloaded(client):
    """反向断言：题面响应零 answer_key 泄漏（QUIZ-001 不变）。"""
    data = _session(client)
    for it in data["items"]:
        assert "answer_key" not in it
        assert "correct_answer" not in it


# —— 一致：结果页顺序 == 作答时顺序 ——
def test_result_order_matches_served_order(client):
    data = _session(client)
    served = {it["id"]: it["options"] for it in data["items"]}
    for it in data["items"]:
        assert client.post("/api/quiz/answer", json={
            "session_id": data["session_id"], "item_id": it["id"], "my_answer": it["options"][0],
        }).status_code == 200
    res = client.get(f"/api/quiz/session/{data['session_id']}/result").get_json()["data"]
    assert res["items"], "结果页必须有逐题解析"
    for row in res["items"]:
        assert row["options"] == served[row["item_id"]], "结果页顺序必须与作答时一致"
        assert row["correct_answer"] in row["options"], "正确答案必须逐字出现在选项里"
    # 判分仍按文本（QUIZ-004）：选第一项 = 选该位置的文本
    assert res["answered"] == len(data["items"])
