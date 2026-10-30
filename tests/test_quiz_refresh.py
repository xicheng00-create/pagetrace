"""QUIZ-011 一次性脏题刷新：卡文语种=题面语种 + 同 id 覆盖 + quiz_attempts 不变。"""
import json
import logging
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from services import quizgen

from scripts import ingest_store
from scripts import refresh_stale_quiz_items as refresh


def _seed_con(tmp_path, monkeypatch):
    """2 卡 2 题：卡1 中文卡却挂着 True/False；卡2 英文卡却挂着汉字题面（都是脏题）。"""
    monkeypatch.setattr(quizgen, "_chat", lambda _m: None)   # 机械派生，不触网
    con = ingest_store.connect(str(tmp_path / "r.sqlite3"))
    con.execute("INSERT INTO subjects(id,name,slug,order_no,created_at) VALUES(1,'psy','demo',0,'t')")
    con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,1,1,'b','book','active','t')")
    con.execute("INSERT INTO chapters(id,book_id,name,order_no,anchor,status,unlocked_at) VALUES(1,1,'ch',1,'ch','unlocked','t')")
    con.execute("INSERT INTO concepts(id,concept_uid,chapter_id,name) VALUES(1,'c1',1,'概念A')")
    con.execute("INSERT INTO concepts(id,concept_uid,chapter_id,name) VALUES(2,'c2',1,'概念B')")
    zh_hash = ingest_store.content_hash("组合治理", "选择投资")
    en_hash = ingest_store.content_hash("Portfolio governance", "Select investments")
    con.execute("INSERT INTO cards(id,concept_id,subject_id,front,back,source,content_hash,status,learn_count,created_at)"
                " VALUES(1,1,1,'组合治理','选择投资','s',?,'reviewing',1,'t')", (zh_hash,))
    con.execute("INSERT INTO cards(id,concept_id,subject_id,front,back,source,content_hash,status,learn_count,created_at)"
                " VALUES(2,2,1,'Portfolio governance','Select investments','s',?,'reviewing',1,'t')", (en_hash,))
    con.execute("INSERT INTO quiz_items(id,card_id,type,stem,options,answer_key,points,source,content_hash,card_content_hash,created_at)"
                " VALUES(1,1,'bool','判断：选择投资','[\"True\",\"False\"]','True',1,'fallback','qh1',?,'t')", (zh_hash,))
    con.execute("INSERT INTO quiz_items(id,card_id,type,stem,options,answer_key,points,source,content_hash,card_content_hash,created_at)"
                " VALUES(2,2,'bool','判断：Select investments','[\"True\",\"False\"]','True',1,'fallback','qh2',?,'t')", (en_hash,))
    con.execute("INSERT INTO quiz_attempts(user_id,item_id,card_id,session_id,my_answer,is_correct,created_at) VALUES(1,1,1,'s1','对',0,'2026-09-27T00:00:00+00:00')")
    con.execute("INSERT INTO quiz_attempts(user_id,item_id,card_id,session_id,my_answer,is_correct,created_at) VALUES(1,2,2,'s2','True',1,'2026-09-27T00:00:00+00:00')")
    con.commit()
    return con


def test_is_stale_language_boundaries():
    assert refresh.is_stale({"front": "Portfolio governance", "back": "Select investments"},
                            "判断：Select investments", ["True", "False"]) is True   # 英文卡 + 汉字题面
    assert refresh.is_stale({"front": "Portfolio governance", "back": "Select investments"},
                            "True or False: Select investments", ["True", "False"]) is False
    assert refresh.is_stale({"front": "组合治理", "back": "选择投资"},
                            "判断：选择投资", ["True", "False"]) is True               # 中文卡 + True/False
    assert refresh.is_stale({"front": "组合治理", "back": "选择投资"},
                            "判断：选择投资", ["对", "错"]) is False


def test_refresh_regen_in_place_preserves_attempts(tmp_path, monkeypatch):
    con = _seed_con(tmp_path, monkeypatch)
    stale = refresh.refresh(con, apply=False)
    assert [r["id"] for r in stale] == [1, 2]

    refresh.refresh(con, apply=True)
    # 不删不插：行数与 id 全保留
    rows = {r["id"]: r for r in con.execute("SELECT id, card_id, type, stem, options FROM quiz_items").fetchall()}
    assert set(rows) == {1, 2}
    assert json.loads(rows[1]["options"]) == ["对", "错"]                       # 中文卡 → 对/错
    assert not refresh.has_cjk(rows[2]["stem"])                                  # 英文卡 → 题面无汉字
    assert con.execute("SELECT COUNT(*) FROM quiz_attempts").fetchone()[0] == 2  # 作答行数与关联不变
    assert {r["item_id"] for r in con.execute("SELECT item_id FROM quiz_attempts").fetchall()} == {1, 2}
    assert refresh.stale_rows(con) == []                                        # 刷新后无残留脏题


# —— QUIZ-012：机械降级的选择题也算脏题（干扰项毒化） ——

def _seed_fallback_choice(tmp_path):
    """1 章 2 卡 + 1 道 source='fallback' 的选择题（选项里混着「了解（knowledge）」这类纯标签）。"""
    con = ingest_store.connect(str(tmp_path / "fb.sqlite3"))
    con.execute("INSERT INTO subjects(id,name,slug,order_no,created_at) VALUES(1,'psy','demo',0,'t')")
    con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,1,1,'b','book','active','t')")
    con.execute("INSERT INTO chapters(id,book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,1,'ch',1,'ch','unlocked','t')")
    backs = {1: "伴侣之间在六个方面存在程度差异，未必全部出现。", 2: "低自尊者会低估伴侣的爱。"}
    con.execute("INSERT INTO concepts(id,concept_uid,chapter_id,name) VALUES(1,'c1',1,'概念A')")
    con.execute("INSERT INTO concepts(id,concept_uid,chapter_id,name) VALUES(2,'c2',1,'概念B')")
    for cid, back in backs.items():
        con.execute("INSERT INTO cards(id,concept_id,subject_id,front,back,source,content_hash,status,"
                    "learn_count,created_at) VALUES(?,?,1,?,?,'s',?,'reviewing',1,'t')",
                    (cid, cid, f"概念{cid}的要点？", back, ingest_store.content_hash(f"概念{cid}的要点？", back)))
    con.execute("INSERT INTO quiz_items(id,card_id,type,stem,options,answer_key,points,source,content_hash,"
                "card_content_hash,created_at) VALUES(1,1,'choice','概念1的要点？',?,?,1,'fallback','qh1','ch1','t')",
                (json.dumps(["了解（knowledge）", "关心（care）", backs[1]], ensure_ascii=False), backs[1]))
    con.execute("INSERT INTO quiz_attempts(user_id,item_id,card_id,session_id,my_answer,is_correct,created_at) VALUES(1,1,1,'s1','关心（care）',0,'2026-10-03T00:00:00+00:00')")
    con.commit()
    return con


def test_reason_of_covers_fallback_choice():
    card = {"front": "概念1的要点？", "back": "伴侣之间在六个方面存在程度差异，未必全部出现。"}
    row = {"type": "choice", "source": "fallback", "stem": card["front"],
           "options": json.dumps(["了解（knowledge）", "关心（care）"], ensure_ascii=False)}
    assert refresh.reason_of(card, row) == "fallback_choice"
    assert refresh.reason_of(card, dict(row, source="ai")) is None
    assert refresh.reason_of(card, dict(row, type="bool", options=json.dumps(["对", "错"]))) is None


def test_refresh_regenerates_fallback_choice_in_place(tmp_path, monkeypatch):
    """QUIZ-012：机械降级选择题 → 同 id 覆盖重生为真选择题（LLM 可用），作答行数不变。"""
    con = _seed_fallback_choice(tmp_path)
    monkeypatch.setattr(quizgen, "_chat", lambda _m: json.dumps({"items": [{
        "card_id": 1, "type": "choice", "stem": "伴侣之间在六个方面存在什么差异？",
        "options": ["只在少数方面存在差异，且必然全部出现。", "存在程度差异，未必全部出现。"],
        "answer_key": "存在程度差异，未必全部出现。"}]}, ensure_ascii=False))
    stale = refresh.refresh(con, apply=False)
    assert [(r["id"], r["reason"]) for r in stale] == [(1, "fallback_choice")]

    refresh.refresh(con, apply=True)
    row = con.execute("SELECT id, source, type, options FROM quiz_items").fetchone()
    assert (row["id"], row["source"], row["type"]) == (1, "ai", "choice")
    assert all(not quizgen.is_gloss_label(o) for o in json.loads(row["options"]))
    assert con.execute("SELECT COUNT(*) FROM quiz_attempts").fetchone()[0] == 1
    assert refresh.stale_rows(con) == []


def test_refresh_keeps_warning_when_llm_still_wrong_type(tmp_path, monkeypatch, caplog):
    """QUIZ-012：刷新后仍题型不符（LLM 不可用）→ 不崩，只 warning（脚本不许把 LLM 故障当刷新失败）。"""
    con = _seed_fallback_choice(tmp_path)
    monkeypatch.setattr(quizgen, "_chat", lambda _m: None)   # LLM 不可用 → 机械派生
    with caplog.at_level(logging.WARNING):
        refresh.refresh(con, apply=True)
    assert any("机械降级选择题" in r.getMessage() for r in caplog.records)
    row = con.execute("SELECT id, source, type FROM quiz_items").fetchone()
    assert (row["id"], row["source"]) == (1, "fallback")     # 仍是机械题，但没崩、没删行
    assert con.execute("SELECT COUNT(*) FROM quiz_attempts").fetchone()[0] == 1
