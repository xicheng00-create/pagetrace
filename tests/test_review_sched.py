"""段④ 复习调度（REVIEW-001）：三档结果推进 + 单一间隔表 + 落库历史。"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from config import BaseConfig  # noqa: E402
from services import review_sched  # noqa: E402

from scripts import ingest_kb  # noqa: E402


def test_good_advances_and_masters():
    st, lc, _ = review_sched.compute({"learn_count": 0}, "good")
    assert (st, lc) == ("reviewing", 1)
    st, lc, _ = review_sched.compute({"learn_count": BaseConfig.MASTER_MIN_LEARN - 1}, "good")
    assert st == "mastered" and lc == BaseConfig.MASTER_MIN_LEARN


def test_again_keeps_count_and_learning():
    st, lc, nxt = review_sched.compute({"learn_count": 4}, "again")
    assert st == "learning" and lc == 4 and nxt


def test_hard_advances_to_review():
    st, lc, _ = review_sched.compute({"learn_count": 0}, "hard")
    assert st == "reviewing" and lc == 1


def test_illegal_result_raises():
    with pytest.raises(ValueError):
        review_sched.compute({}, "meh")


def test_apply_result_writes_history_and_state(tmp_path):
    con = ingest_kb.connect(str(tmp_path / "s.sqlite3"))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('x','x',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'b','b','active','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at) VALUES(1,'c',1,'c','unlocked','t')")
    con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('c1',1,'cp')")
    con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                "learn_count,next_review_at,created_at) VALUES(1,1,'q','a','s','h','new',0,NULL,'t')")
    con.commit()
    state = review_sched.apply_result(con, 1, "good", user_id=1)
    assert state["learn_count"] == 1 and state["status"] == "reviewing"
    hist = con.execute("SELECT result, status FROM card_reviews WHERE card_id=1").fetchone()
    assert hist["result"] == "good" and hist["status"] == "reviewing"
    assert review_sched.apply_result(con, 999, "good", user_id=1) is None
    con.close()
