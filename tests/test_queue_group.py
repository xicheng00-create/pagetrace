import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))
from services.queue import today_queue
from services.clock import TZ8
import importlib.util
spec=importlib.util.spec_from_file_location("test_today", Path(__file__).parent / "test_today.py")
_seed=importlib.util.module_from_spec(spec); spec.loader.exec_module(_seed)
_seed=_seed._seed

AT = datetime(2026, 10, 9, 12, tzinfo=TZ8).isoformat()

def _data(tmp_path, n):
    con = _seed(tmp_path, unlocked=(1,), ch1_cards=n, ch2_cards=0)
    con.execute("UPDATE cards SET status='reviewing',next_review_at=?", ('2026-10-09T10:00:00+08:00',))
    con.commit()
    return con

def _review(con, ids, result='good', learned=AT, nxt='2026-10-10T12:00:00+08:00'):
    for i in ids:
        con.execute('UPDATE cards SET next_review_at=? WHERE id=?',(nxt,i))
        con.execute('INSERT INTO card_reviews(user_id,card_id,learned_at,result,status) VALUES(1,?,?,?,?)',(i,learned,result,'reviewing'))
    con.commit()

def test_ten_passed_removed_and_remaining_20(tmp_path):
    con=_data(tmp_path,30); _review(con,range(1,11),nxt='2026-10-11T12:00:00+08:00'); q=today_queue(con,at=AT,target=30)
    assert q['group']['done']==10 and len(q['due'])+len(q['new'])==20
    assert not set(range(1,11)) & {x['card_id'] for x in q['due']+q['new']}

def test_again_does_not_count_and_returns_when_due(tmp_path):
    con=_data(tmp_path,15); _review(con,range(1,11));
    for i in range(1,4): _review(con,[i],result='again',nxt='2026-10-09T11:00:00+08:00')
    q=today_queue(con,at=AT,target=30)
    assert q['group']['done']==7
    assert set(range(1,4)) <= {x['card_id'] for x in q['due']+q['new']}

def test_thirty_done_zero(tmp_path):
    con=_data(tmp_path,30); _review(con,range(1,31),nxt='2026-10-11T12:00:00+08:00'); q=today_queue(con,at=AT,target=30)
    assert q['group']['done']==30 and not q['due'] and not q['new']

def test_extra_group_still_excludes_passed(tmp_path):
    con=_data(tmp_path,35); _review(con,range(1,11),nxt='2026-10-11T12:00:00+08:00'); q=today_queue(con,at=AT,target=30,extra=True)
    assert len(q['due'])+len(q['new'])==25
    assert not set(range(1,11)) & {x['card_id'] for x in q['due']+q['new']}

def test_yesterday_not_counted(tmp_path):
    con=_data(tmp_path,20); _review(con,range(1,11),learned='2026-10-08T23:59:00+08:00')
    assert today_queue(con,at=AT,target=30)['group']['done']==0

def test_again_card_outranks_older_overdue_when_capped(tmp_path):
    """cap 截断时，今日判「忘了」的卡必须优先回队（否则被老卡挤掉、当天永远考不到）。"""
    con=_data(tmp_path,20)
    _review(con,range(1,4),result='again',nxt='2026-10-09T11:00:00+08:00')   # 3 张 again：更晚到期
    q=today_queue(con,at=AT,target=5)
    got={x['card_id'] for x in q['due']}
    assert set(range(1,4)) <= got, got
    assert len(q['due'])==5, q['due']

