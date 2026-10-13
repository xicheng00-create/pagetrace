"""段⑤A 今日队列：到期优先 + 新卡补齐 + **只取已解锁章**。

反向断言①：未解锁章的卡不得出现在今日队列（也不得出现在测验，见 test_quiz）。
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from services import queue  # noqa: E402

from scripts import ingest_kb  # noqa: E402


def _seed(tmp_path, unlocked=(1,), ch1_cards=3, ch2_cards=2):
    """1 学科 / 1 书 / 2 章；按 unlocked 决定章是否解锁。"""
    con = ingest_kb.connect(str(tmp_path / "q.sqlite3"))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('psy','demo',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'书','book','active','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,'第1章',1,'第1章','unlocked','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,'第2章',2,'第2章','unlocked',NULL)")
    cid1 = con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('a',1,'概念A')").lastrowid
    cid2 = con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('b',2,'概念B')").lastrowid
    n = 0
    for cid, count in ((cid1, ch1_cards), (cid2, ch2_cards)):
        for _ in range(count):
            n += 1
            con.execute(
                "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                "learn_count,next_review_at,created_at) VALUES(?,1,?,?,'s',?,'new',0,NULL,'t')",
                (cid, f"q{n}", f"a{n}", f"h{n}"))
    if 1 in unlocked:
        con.execute("UPDATE chapters SET unlocked_at='t', status='unlocked' WHERE order_no=1")
    if 2 in unlocked:
        con.execute("UPDATE chapters SET unlocked_at='t', status='unlocked' WHERE order_no=2")
    con.commit()
    return con


def test_new_cards_fill_queue(tmp_path):
    con = _seed(tmp_path, ch1_cards=3, ch2_cards=2)
    q = queue.today_queue(con, user_id=1)
    assert q["due"] == [] and [c["chapter"] for c in q["new"]] == ["第1章"] * 3
    con.close()


def test_reverse_assertion_locked_chapter_excluded(tmp_path):
    """第 2 章锁定（已学 0）→ 它的卡不得出现在今日队列。"""
    con = _seed(tmp_path, unlocked=(1,), ch1_cards=3, ch2_cards=2)
    q = queue.today_queue(con, user_id=1)
    assert q["new"] and all(c["chapter_id"] == 1 for c in q["new"])
    assert 2 not in {c["chapter_id"] for c in (q["due"] + q["new"])}
    con.close()


def test_due_first_and_ordering(tmp_path):
    con = _seed(tmp_path, ch1_cards=3, ch2_cards=0)
    # 两张到期，next_review_at 一前一后
    con.execute("UPDATE cards SET status='learning', next_review_at='2000-01-02T00:00:00+08:00' WHERE id=2")
    con.execute("UPDATE cards SET status='learning', next_review_at='2000-01-01T00:00:00+08:00' WHERE id=3")
    con.commit()
    q = queue.today_queue(con, user_id=1)
    assert [c["card_id"] for c in q["due"]] == [3, 2]  # 升序
    assert [c["card_id"] for c in q["new"]] == [1]
    con.close()


def test_batch_limits(tmp_path):
    con = _seed(tmp_path, ch1_cards=5, ch2_cards=0)
    q = queue.today_queue(con, batch_max=4, new_max=2, user_id=1)
    assert len(q["new"]) == 2  # new_max 生效
    q2 = queue.today_queue(con, batch_max=2, new_max=10, user_id=1)
    assert len(q2["new"]) == 2  # batch_max 与 new_max 取小
    # 到期占满 batch → 新卡为 0
    con.execute("UPDATE cards SET status='reviewing', next_review_at='2000-01-01T00:00:00+08:00'")
    con.commit()
    q3 = queue.today_queue(con, batch_max=5, new_max=10, user_id=1)
    assert len(q3["due"]) == 5 and q3["new"] == []
    con.close()


def test_subject_filter(tmp_path):
    con = _seed(tmp_path, ch1_cards=2, ch2_cards=0)
    assert queue.today_queue(con, subject_id=1, user_id=1)["new"] != []
    assert queue.today_queue(con, subject_id=999, user_id=1)["new"] == []
    con.close()
