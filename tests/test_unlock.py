"""段④ 解锁（SCHED-001/002/005）：达标解锁 + **反向断言**（未达阈值不得解锁）+ 单向。"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from services import unlock  # noqa: E402

from scripts import ingest_kb  # noqa: E402


def _seed(tmp_path, n_cards=5, book="全书"):
    """建 1 学科 / 1 书 / 2 章 / 1 概念 / n_cards 张卡（初始 new）。"""
    con = ingest_kb.connect(str(tmp_path / "u.sqlite3"))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('演示学科','demo',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'书','book','active','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status) VALUES(1,'第1章',1,'第1章','locked')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status) VALUES(1,'第2章',2,'第2章','locked')")
    con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('c1',1,'概念')")
    for i in range(n_cards):
        con.execute(
            "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
            "learn_count,next_review_at,created_at) VALUES(1,1,?,?,'s',?,'new',0,NULL,'t')",
            (f"q{i}", f"a{i}", f"h{i}"))
    con.commit()
    return con


def _set(con, status, mastered=0, due=0, total=None):
    """把前 mastered 张设 mastered、再 due 张设到期 learning，其余 new。"""
    con.execute("UPDATE cards SET status='new', learn_count=0, next_review_at=NULL")
    ids = [r[0] for r in con.execute("SELECT id FROM cards ORDER BY id").fetchall()]
    for cid in ids[:mastered]:
        con.execute("UPDATE cards SET status='mastered', learn_count=3, next_review_at='2999-01-01T00:00:00+08:00' WHERE id=?", (cid,))
        con.execute("INSERT INTO card_reviews(user_id,card_id,learned_at,result,status) VALUES(1,?, '2026-09-28T12:00:00+08:00', 'good', 'mastered')", (cid,))
    for cid in ids[mastered:mastered + due]:
        con.execute("UPDATE cards SET status='learning', learn_count=1, next_review_at='2000-01-01T00:00:00+08:00' WHERE id=?", (cid,))
    con.commit()
    return ids


def test_first_chapter_unlocked_new_book(tmp_path):
    con = _seed(tmp_path)
    unlock.maybe_unlock(con)
    rows = con.execute("SELECT order_no, unlocked_at FROM chapters ORDER BY order_no").fetchall()
    assert rows[0]["unlocked_at"] and rows[1]["unlocked_at"] is None
    con.close()


def test_small_chapter_unlocks_when_mastered(tmp_path):
    """小章门槛取卡数：4 张全掌握即可解锁。"""
    con = _seed(tmp_path, n_cards=4)
    _set(con, "mastered", mastered=4)
    unlocked = unlock.maybe_unlock(con)
    assert 2 in unlocked
    row = con.execute("SELECT unlocked_at FROM chapters WHERE order_no=2").fetchone()
    assert row["unlocked_at"] is not None
    con.close()


def test_reverse_assertion_mastery_below_ratio_not_unlocked(tmp_path):
    """已学 5 张但掌握度 60% < 80% → 不解锁。"""
    con = _seed(tmp_path, n_cards=5)
    _set(con, "mastered", mastered=3)  # 3/5 = 60%
    assert 2 not in unlock.maybe_unlock(con)
    assert con.execute("SELECT unlocked_at FROM chapters WHERE order_no=2").fetchone()["unlocked_at"] is None
    con.close()


def test_reverse_assertion_due_nonzero_not_unlocked(tmp_path):
    """掌握度达标但本章仍有到期未复习 → 不解锁。"""
    con = _seed(tmp_path, n_cards=5)
    _set(con, "mastered", mastered=5, due=0)
    # 再造 1 张到期：mastered 卡到期也算 due
    con.execute("UPDATE cards SET next_review_at='2000-01-01T00:00:00+08:00' WHERE id=1")
    con.commit()
    ok, why = unlock.is_ready(con, 1)
    assert ok is False and "到期" in why
    assert 2 not in unlock.maybe_unlock(con)
    con.close()


def test_unlock_when_thresholds_met(tmp_path):
    """已学 5 且全掌握且到期 0 → 第 2 章解锁（SCHED-001 正例）。"""
    con = _seed(tmp_path, n_cards=5)
    _set(con, "mastered", mastered=5)
    unlocked = unlock.maybe_unlock(con)
    assert 2 in unlocked
    assert con.execute("SELECT unlocked_at FROM chapters WHERE order_no=2").fetchone()["unlocked_at"]
    con.close()


def test_unlock_is_one_way(tmp_path):
    """SCHED-002：解锁后掌握度回落不重新上锁。"""
    con = _seed(tmp_path, n_cards=5)
    _set(con, "mastered", mastered=5)
    unlock.maybe_unlock(con)
    # 回落：1 张降为 learning 且到期
    con.execute("UPDATE cards SET status='learning', next_review_at='2000-01-01T00:00:00+08:00' WHERE id=1")
    con.commit()
    assert unlock.maybe_unlock(con) == []
    assert con.execute("SELECT unlocked_at FROM chapters WHERE order_no=2").fetchone()["unlocked_at"]
    con.close()


def test_stats_and_missing_chapter(tmp_path):
    con = _seed(tmp_path, n_cards=5)
    s = unlock.chapter_stats(con, 1)
    assert s == {"learned": 0, "mastered": 0, "due": 0, "total": 5, "ratio": 0.0}
    assert unlock.unlock_chapter(con, 999) is False  # 不存在的章
    assert unlock.is_ready(con, 1, ratio=0.0, min_learned=0)[0] is False
    con.close()


# —— 0.4.1（DATA-005）：多书场景下 maybe_unlock 行为零变化 ——

def _seed_two_books(tmp_path, ch1_cards=5):
    """1 学科 / 2 书 / 每书 2 章；两书各 1 概念 + ch1_cards 张卡（初始 new）。"""
    con = ingest_kb.connect(str(tmp_path / "two.sqlite3"))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('演示学科','demo',0,'t')")
    for bid, title in ((1, "书A"), (2, "书B")):
        con.execute("INSERT INTO books(owner_id,id,subject_id,title,slug,status,created_at) VALUES(1,?,1,?,?,'active','t')", (bid, title, title))
        con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status)"
                    " VALUES(?,'第1章',1,'第1章','locked')", (bid,))
        con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status)"
                    " VALUES(?,'第2章',2,'第2章','locked')", (bid,))
        cid = con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES(?,?,'概念')",
                          (f"c{bid}", con.execute(
                              "SELECT id FROM chapters WHERE book_id=? AND order_no=1", (bid,)
                          ).fetchone()[0])).lastrowid
        for i in range(ch1_cards):
            con.execute(
                "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                "learn_count,next_review_at,created_at) VALUES(?,1,?,?,'s',?,'new',0,NULL,'t')",
                (cid, f"b{bid}q{i}", f"b{bid}a{i}", f"b{bid}h{i}"))
    con.commit()
    return con


def test_two_books_each_unlock_only_first_chapter(tmp_path):
    """0.4.1 反向断言：多书时 maybe_unlock 行为零变化 —— 两书各自只解锁首章。"""
    con = _seed_two_books(tmp_path)
    unlock.maybe_unlock(con)
    for bid in (1, 2):
        rows = con.execute("SELECT order_no, unlocked_at FROM chapters WHERE book_id=?"
                           " ORDER BY order_no", (bid,)).fetchall()
        assert rows[0]["unlocked_at"], f"书{bid} 首章应解锁"
        assert rows[1]["unlocked_at"] is None, f"书{bid} 第2章不应解锁"
    con.close()


def test_two_books_chain_still_by_order_and_threshold(tmp_path):
    """连锁解锁仍按章序、仍受阈值约束：只把书A 推过阈值，书B 不受影响。"""
    con = _seed_two_books(tmp_path)
    # 书A 的 5 张全部推过阈值（mastered 且不到期）
    con.execute("UPDATE cards SET status='mastered', learn_count=3,"
                " next_review_at='2999-01-01T00:00:00+08:00' WHERE front LIKE 'b1q%'")
    for row in con.execute("SELECT id FROM cards WHERE front LIKE 'b1q%'"):
        con.execute("INSERT INTO card_reviews(user_id,card_id,learned_at,result,status) VALUES(1,?, '2026-09-28T12:00:00+08:00', 'good', 'mastered')", (row[0],))
    con.commit()
    unlock.maybe_unlock(con)
    a = con.execute("SELECT order_no, unlocked_at FROM chapters WHERE book_id=1 ORDER BY order_no").fetchall()
    b = con.execute("SELECT order_no, unlocked_at FROM chapters WHERE book_id=2 ORDER BY order_no").fetchall()
    assert a[0]["unlocked_at"] and a[1]["unlocked_at"], "书A 达标应连锁解锁第2章"
    assert b[0]["unlocked_at"] and b[1]["unlocked_at"] is None, "书B 未达标，不得解锁第2章"
    con.close()
