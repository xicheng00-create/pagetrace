"""TASK-001 今日任务：构成（复习 N / 出题 M）、完成判定、稳定性、不除零。

口径：N = 当天到期卡数（当前到期 ∪ 今日已复习，一天内稳定）；M = 配置化目标题数；
done = 复习完成数 ≥ N 且 测验完成数 ≥ M。
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from config import BaseConfig  # noqa: E402
from scripts import ingest_kb  # noqa: E402
from services import queue, tasks  # noqa: E402
from services.clock import TZ8, iso  # noqa: E402

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=TZ8)


def _seed(db, *, due=3, learned=0):
    """1 学科 / 1 书 / 1 章（已解锁）/ 1 概念 / due 张到期卡（status='reviewing'）。返回卡 id 列表。"""
    con = ingest_kb.connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('合成示例书12','demo',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'书','book','active','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,'第1章',1,'第1章','unlocked','t')")
    cid = con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('c1',1,'概念')").lastrowid
    ids = []
    for i in range(due):
        st = 'mastered' if i < learned else 'reviewing'
        ids.append(con.execute(
            "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
            "learn_count,next_review_at,created_at)"
            " VALUES(?,1,?,?,'s',?,?,1,'2020-01-01T00:00:00+08:00','t')",
            (cid, f"q{i}", f"a{i}", f"h{i}", st)).lastrowid)
    con.commit()
    return con, ids


def _review(con, card_ids, when=NOW):
    for cid in card_ids:
        con.execute("INSERT INTO card_reviews(user_id,card_id,learned_at,result,next_review_at,learn_count,status) VALUES(1,?,?,'good',NULL,1,'reviewing')", (cid, iso(when)))
    con.commit()


def _quiz(con, n, when=NOW):
    """插入 n 道题 + n 条今日作答（distinct item_id）。"""
    utc = when.astimezone(timezone.utc).isoformat(timespec="seconds")
    card = con.execute("SELECT id FROM cards LIMIT 1").fetchone()[0]
    for i in range(n):
        iid = con.execute(
            "INSERT INTO quiz_items(card_id,type,stem,options,answer_key,points,source,content_hash,"
            "created_at) VALUES(?,?,?,?,?,1,'fallback',?,?)",
            (card, "bool", f"题{i}", '["对","错"]', "对", f"qh{i}", "t")).lastrowid
        con.execute('INSERT INTO quiz_attempts(user_id,item_id,card_id,session_id,my_answer,is_correct,created_at) VALUES(1,?,?,?,?,1,?)', (iid, card, f"s{i}", "对", utc))
    con.commit()


def test_before_any_work_not_done(tmp_path):
    con, _ = _seed(tmp_path / "t.sqlite3")
    r = tasks.today_task(con, at=NOW, quiz_target=10)
    assert r["review"] == {"target": 3, "done": 0, "complete": False, "reason": ""}
    assert r["quiz"] == {"target": 10, "done": 0, "complete": False}
    assert r["done"] is False
    con.close()


def test_partial_review_target_stable(tmp_path):
    """复习 1 张后：目标仍是 3（一天内稳定），完成数 1 → 未完成。"""
    con, ids = _seed(tmp_path / "t.sqlite3")
    _review(con, ids[:1])
    r = tasks.today_task(con, at=NOW, quiz_target=10)
    assert r["review"]["target"] == 3 and r["review"]["done"] == 1
    assert r["review"]["complete"] is False
    con.close()


def test_done_when_review_and_quiz_reach_targets(tmp_path):
    con, ids = _seed(tmp_path / "t.sqlite3")
    _review(con, ids)          # 复习 3
    _quiz(con, 10)             # 测验 10
    r = tasks.today_task(con, at=NOW, quiz_target=10)
    assert r["review"] == {"target": 3, "done": 3, "complete": True, "reason": ""}
    assert r["quiz"] == {"target": 10, "done": 10, "complete": True}
    assert r["done"] is True
    con.close()


def test_quiz_short_of_target_not_done(tmp_path):
    con, ids = _seed(tmp_path / "t.sqlite3")
    _review(con, ids)
    _quiz(con, 9)
    r = tasks.today_task(con, at=NOW, quiz_target=10)
    assert r["review"]["complete"] is True and r["quiz"]["complete"] is False
    assert r["done"] is False
    con.close()


def test_zero_cards_no_divide_and_review_complete(tmp_path):
    """无卡：目标 0、完成 0、复习子项视为完成（0 ≥ 0）；退化态带非空 reason，不除零、不抛异常。"""
    con, _ = _seed(tmp_path / "t.sqlite3", due=0)
    r = tasks.today_task(con, at=NOW, quiz_target=10)
    assert r["review"]["target"] == 0 and r["review"]["done"] == 0
    assert r["review"]["complete"] is True and r["review"]["reason"].strip()
    assert r["done"] is False           # 出题未达标
    con.close()


def test_quiz_target_configurable(tmp_path):
    con, ids = _seed(tmp_path / "t.sqlite3")
    _review(con, ids)
    _quiz(con, 3)
    assert tasks.today_task(con, at=NOW, quiz_target=3)["done"] is True
    assert tasks.today_task(con, at=NOW, quiz_target=4)["done"] is False
    con.close()


def test_default_quiz_target_from_config(tmp_path):
    con, _ = _seed(tmp_path / "t.sqlite3")
    r = tasks.today_task(con, at=NOW)
    assert r["quiz"]["target"] == BaseConfig.QUIZ_TASK_TARGET
    con.close()


def test_yesterday_reviews_do_not_count(tmp_path):
    """昨天的复习记录不计入今日完成数（本地日切）。"""
    from datetime import timedelta
    con, ids = _seed(tmp_path / "t.sqlite3")
    _review(con, ids, when=NOW - timedelta(days=1))
    r = tasks.today_task(con, at=NOW, quiz_target=10)
    assert r["review"]["done"] == 0
    con.close()


def test_api_endpoint(tmp_path, monkeypatch):
    from app import create_app
    db = tmp_path / "api.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con, _ = _seed(db)
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/task")
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert d["review"]["target"] == 3 and d["quiz"]["target"] == BaseConfig.QUIZ_TASK_TARGET
        assert d["done"] is False


# —— GOAL-001（v0.6.0）：今日复习目标 = min(REVIEW_TASK_TARGET, 今日可复习总数) ——
def _seed_pool(db, *, due=0, new=0):
    """1 学科 / 1 书 / 1 章（已解锁）/ 1 概念；`due` 张到期 + `new` 张未学新卡。"""
    con = ingest_kb.connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('合成示例书12','demo',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'书','book','active','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,'第1章',1,'第1章','unlocked','t')")
    cid = con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('c1',1,'概念')").lastrowid
    ids = []
    for i in range(due):
        ids.append(con.execute(
            "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
            "learn_count,next_review_at,created_at)"
            " VALUES(?,1,?,?,'s',?,'reviewing',1,'2020-01-01T00:00:00+08:00','t')",
            (cid, f"d{i}", f"a{i}", f"dh{i}")).lastrowid)
    for i in range(new):
        ids.append(con.execute(
            "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
            "learn_count,next_review_at,created_at)"
            " VALUES(?,1,?,?,'s',?,'new',0,NULL,'t')",
            (cid, f"n{i}", f"b{i}", f"nh{i}")).lastrowid)
    con.commit()
    return con, ids


def test_goal_target_capped_at_30_and_due_first(tmp_path):
    """到期 1 + 新卡足 → target=30（min 上限），且队列首张为到期。"""
    con, ids = _seed_pool(tmp_path / "g.sqlite3", due=1, new=35)
    r = tasks.today_task(con, at=NOW, quiz_target=10)
    assert r["review"]["target"] == 30 and r["review"]["reason"] == ""
    q = queue.today_queue(con, target=r["review"]["target"], user_id=1)
    assert q["due"][0]["card_id"] == ids[0]
    assert len(q["due"]) + len(q["new"]) == 30
    con.close()


def test_goal_target_fills_to_available_when_new_short(tmp_path):
    """到期 1 + 新卡 5（不足 30）→ target 补到可用数 6；队列总数 == target。"""
    con, _ = _seed_pool(tmp_path / "g2.sqlite3", due=1, new=5)
    r = tasks.today_task(con, at=NOW, quiz_target=10)
    assert r["review"]["target"] == 6
    q = queue.today_queue(con, target=r["review"]["target"], user_id=1)
    assert len(q["due"]) + len(q["new"]) == 6
    con.close()


def test_goal_degenerate_target0_and_reason_nonempty(tmp_path):
    """可用 0 → target=0 且 reason 非空（供 UI-003 置灰文案）；队列为空。"""
    con, _ = _seed_pool(tmp_path / "g3.sqlite3", due=0, new=0)
    r = tasks.today_task(con, at=NOW, quiz_target=10)
    assert r["review"]["target"] == 0 and r["review"]["reason"].strip()
    assert queue.today_queue(con, target=0, user_id=1) == {"due": [], "new": [], "group": {"target": 0, "done": 0, "remaining": 0}}
    con.close()


def test_review_target_single_source_config(tmp_path, monkeypatch):
    """目标只认 `BaseConfig.REVIEW_TASK_TARGET`（单一真相）：改配置即改目标。"""
    con, _ = _seed_pool(tmp_path / "g4.sqlite3", due=0, new=10)
    monkeypatch.setattr(BaseConfig, "REVIEW_TASK_TARGET", 5)
    assert tasks.today_task(con, at=NOW, quiz_target=10)["review"]["target"] == 5
    con.close()


def test_review_task_target_env_override():
    """`REVIEW_TASK_TARGET` 环境变量在 import 期生效（env 覆写）。"""
    import os
    import subprocess
    env = {**os.environ, "REVIEW_TASK_TARGET": "7"}
    out = subprocess.run(
        [sys.executable, "-c", "import config; print(config.BaseConfig.REVIEW_TASK_TARGET)"],
        cwd=str(BACKEND), env=env, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == "7"
