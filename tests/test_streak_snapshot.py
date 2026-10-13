"""STREAK-003 snapshot contract tests."""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import sqlite3

from config import BaseConfig
from data import models
from services import streak, tasks
from services.clock import TZ8


def _con(tmp_path, cards=28):
    con = sqlite3.connect(tmp_path / "s.sqlite3")
    con.row_factory = sqlite3.Row
    from data.s2_schema import fresh_schema
    con.executescript(fresh_schema())
    con.execute("INSERT INTO users VALUES(1,'owner','test','owner','t')")
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('x','x',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'b','b','active','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at) VALUES(1,'c',1,'c','unlocked','t')")
    con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('c1',1,'cp')")
    for i in range(cards):
        con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,created_at) VALUES(1,1,?,?,?,?,?,?)",
                    (f'q{i}', f'a{i}', 's', f'h{i}', 'new', 't'))
    models.migrate(con)
    con.commit()
    return con


def _finish(con, at, count):
    for card_id in range(1, count + 1):
        con.execute('INSERT INTO card_reviews(user_id,card_id,learned_at,result,status) VALUES(1,?,?,?,?)',
                    (card_id, at.isoformat(), 'good', 'reviewing'))
        con.execute("UPDATE cards SET status='reviewing', next_review_at='2099-01-01T00:00:00+08:00' WHERE id=?", (card_id,))
    for item_id in range(1, 6):
        con.execute('INSERT INTO quiz_attempts(user_id,item_id,card_id,session_id,my_answer,created_at) VALUES(1,?,?,?,?,?)',
                    (item_id, 1, 's', 'a', (at - timedelta(hours=8)).astimezone(UTC).isoformat()))
    con.commit()


def test_28_available_cards_can_complete_streak(tmp_path):
    at = datetime(2026, 9, 28, 12, tzinfo=TZ8)
    con = _con(tmp_path, 28)
    assert tasks.today_task(con, at=at)['review']['target'] == 28
    _finish(con, at, 28)
    result = streak.compute(con, at=at)
    assert result['today_met'] is True and result['days'] >= 1


def test_full_pool_27_reviews_does_not_meet(tmp_path):
    at = datetime(2026, 9, 28, 12, tzinfo=TZ8)
    con = _con(tmp_path, 35)
    _finish(con, at, 27)
    assert streak.compute(con, at=at)['today_met'] is False


def test_snapshot_migration_is_idempotent(tmp_path):
    con = _con(tmp_path)
    before = con.execute('SELECT COUNT(*) FROM streak_days').fetchone()[0]
    models.migrate(con)
    after = con.execute('SELECT COUNT(*) FROM streak_days').fetchone()[0]
    assert before == after


def test_daily_met_snapshot_is_monotonic(tmp_path):
    at = datetime(2026, 9, 28, 12, tzinfo=TZ8)
    con = _con(tmp_path, 28)
    _finish(con, at, 28)
    first = streak.compute(con, at=at)
    assert first["today_met"] is True and first["days"] >= 1
    con.execute("DELETE FROM card_reviews")
    con.execute("DELETE FROM quiz_attempts")
    con.commit()
    second = streak.compute(con, at=at)
    row = con.execute("SELECT met FROM streak_days WHERE day='2026-09-28'").fetchone()
    assert row["met"] == 1 and second["days"] >= first["days"]
    assert second["today_met"] == tasks.today_task(con, at=at)["done"] is False
