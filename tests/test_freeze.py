import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'backend'))
from data.s2_schema import fresh_schema
from services.streak import compute, freeze_status, settle_freezes


def _db():
 c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row; c.executescript(fresh_schema()); c.execute("INSERT INTO users (id, username, password_hash, role, created_at) VALUES(1,'owner','test','owner','t')"); c.execute('CREATE TABLE IF NOT EXISTS streak_freezes(day TEXT PRIMARY KEY,streak_kept INTEGER NOT NULL,created_at TEXT NOT NULL)'); return c

def _day(c,d,met): c.execute('INSERT OR REPLACE INTO streak_days VALUES(1,?,?,?,?,?,?)',(d,30,30,5,met,d+'T23:00:00+08:00'))
def _at(d): return datetime.fromisoformat(d+'T12:00:00+08:00')
def _used(c): return c.execute('select count(*) from streak_freezes').fetchone()[0]
def _rows(c): return c.execute('select day,streak_kept from streak_freezes order by day').fetchall()

def test_initial_three():
 c=_db(); assert freeze_status(c,_at('2026-10-10'))['available']==3

def test_grants_each_five():
 c=_db()
 for i in range(1,11): _day(c,(datetime(2026,10,1)+timedelta(days=i-1)).date().isoformat(),1)
 assert freeze_status(c,_at('2026-10-11'))['granted']==5

def test_frozen_days_count_toward_milestone():
 c=_db()
 for i in range(1,6): _day(c,(datetime(2026,10,1)+timedelta(days=i-1)).date().isoformat(),1)   # 10-01..10-05 达标
 c.execute("insert into streak_freezes values(1,'2026-10-06',5,'t')")                            # 10-06 被冰冻
 for i in range(7,12): _day(c,(datetime(2026,10,1)+timedelta(days=i-1)).date().isoformat(),1)  # 10-07..10-11 达标
 assert _used(c)==1
 assert freeze_status(c,_at('2026-10-12'))['granted']==3+2   # 连续段 11 天（含冰冻日）→ +2

def test_trailing_gap_consumes_and_keeps_streak():
 c=_db(); _day(c,'2026-10-06',1); _day(c,'2026-10-07',1); _day(c,'2026-10-08',1); _day(c,'2026-10-09',0)
 settle_freezes(c,_at('2026-10-10'))
 assert _used(c)==1 and _rows(c)[0]['day']=='2026-10-09'
 assert _rows(c)[0]['streak_kept']==3                        # streak_kept = 冻结前连胜天数，不是缺口长度

def test_historic_gap_never_charged():
 c=_db()
 _day(c,'2026-10-01',1); _day(c,'2026-10-02',1)
 for d in ('2026-10-03','2026-10-04','2026-10-05'): _day(c,d,0)
 for d in ('2026-10-06','2026-10-07','2026-10-08','2026-10-09'): _day(c,d,1)
 st=settle_freezes(c,_at('2026-10-10'))
 assert _used(c)==0 and st['available']==3                   # 旧断点不回溯消耗，冰冻余额原封不动

def test_gap_larger_than_balance_writes_nothing():
 c=_db()
 _day(c,'2026-10-05',1); _day(c,'2026-10-06',1)
 for d in ('2026-10-07','2026-10-08','2026-10-09'): _day(c,d,0)
 for i in range(1,4): c.execute('insert into streak_freezes values(1,?,?,?)',(f'2026-09-0{i}',0,'t'))
 settle_freezes(c,_at('2026-10-10'))
 assert _used(c)==3                                          # 缺口 3 > 余额 0 → 一行都不写

def test_multi_day_gap_fills_all_with_same_kept():
 c=_db()
 _day(c,'2026-10-05',1); _day(c,'2026-10-06',1)
 for d in ('2026-10-07','2026-10-08','2026-10-09'): _day(c,d,0)
 st=settle_freezes(c,_at('2026-10-10'))
 assert _used(c)==3 and st['available']==0
 assert [r['streak_kept'] for r in _rows(c)]==[2,2,2]        # 三天都记「保住 2 天」

def test_repeat_idempotent():
 c=_db(); _day(c,'2026-10-08',1); _day(c,'2026-10-09',0)
 settle_freezes(c,_at('2026-10-10')); settle_freezes(c,_at('2026-10-10'))
 assert _used(c)==1

def test_streak_survives_through_frozen_day():
 c=_db()
 _day(c,'2026-10-07',1); _day(c,'2026-10-08',1)
 _day(c,'2026-10-09',0)
 _day(c,'2026-10-10',1)
 settle_freezes(c,_at('2026-10-10'))                          # 10-10 当天结算：10-09 是最后一段缺口 → 冰住
 assert _used(c)==1
 assert compute(c,_at('2026-10-11'))['days']==4               # 10-10 达标 + 10-09 冰冻 + 10-08/10-07 达标

def test_zero_balance_no_write():
 c=_db(); _day(c,'2026-10-07',1)
 for i in range(3): c.execute('insert into streak_freezes values(1,?,?,?)',(f'2026-10-0{i+1}',0,'t'))
 _day(c,'2026-10-08',0); settle_freezes(c,_at('2026-10-10')); assert _used(c)==3

def test_no_met_day_writes_nothing():
 c=_db()
 for d in ('2026-10-08','2026-10-09'): _day(c,d,0)
 assert settle_freezes(c,_at('2026-10-10'))['available']==3 and _used(c)==0

def test_available_floor_zero():
 c=_db()
 for i in range(1,5): c.execute('insert into streak_freezes values(1,?,?,?)',(f'2026-09-0{i}',0,'t'))
 assert freeze_status(c,_at('2026-10-10'))['available']==0
