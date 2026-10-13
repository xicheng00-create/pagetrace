"""SCOPE-001~003：图书多选复习范围（prefs 持久化 / book_filter 拼装 / 影响队列·任务·出题）。"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from services import queue, quiz, scope, tasks  # noqa: E402

from scripts import ingest_kb  # noqa: E402


def _seed(tmp_path):
    """1 学科 / 2 书 / 每书 1 章；书A = 3 new + 1 learning，书B = 2 new + 1 learning。"""
    con = ingest_kb.connect(str(tmp_path / "scope.sqlite3"))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('psy','psychology',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'书A','a','active','t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'书B','b','active','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(1,'A1',1,'A1','unlocked','t')")
    con.execute("INSERT INTO chapters(book_id,name,order_no,anchor,status,unlocked_at)"
                " VALUES(2,'B1',1,'B1','unlocked','t')")
    cid1 = con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('a',1,'cA')").lastrowid
    cid2 = con.execute("INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('b',2,'cB')").lastrowid
    n = 0
    for _ in range(3):
        n += 1
        con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                    "learn_count,next_review_at,created_at) VALUES(?,1,?,?,'s',?,'new',0,NULL,'t')",
                    (cid1, f"q{n}", f"a{n}", f"h{n}"))
    n += 1
    con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                "learn_count,next_review_at,created_at) VALUES(?,1,?,?,'s',?,'learning',1,NULL,'t')",
                (cid1, f"q{n}", f"a{n}", f"h{n}"))
    for _ in range(2):
        n += 1
        con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                    "learn_count,next_review_at,created_at) VALUES(?,1,?,?,'s',?,'new',0,NULL,'t')",
                    (cid2, f"q{n}", f"a{n}", f"h{n}"))
    n += 1
    con.execute("INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,status,"
                "learn_count,next_review_at,created_at) VALUES(?,1,?,?,'s',?,'learning',1,NULL,'t')",
                (cid2, f"q{n}", f"a{n}", f"h{n}"))
    con.commit()
    return con


def test_scope_persist_and_filter(tmp_path):
    con = _seed(tmp_path)
    assert scope.get_book_scope(con) is None                       # 默认全部
    assert scope.scope_state(con)["label"] == "图书：全部"

    scope.set_book_scope(con, [1])
    con.commit()
    assert scope.get_book_scope(con) == [1]
    assert scope.scope_state(con)["label"] == "图书：1/2 本（书A）"

    # SCOPE-003（修订）：空集合不是合法状态——写入 "[]" 后读取归一为「全部」并删脏行
    scope.set_book_scope(con, [])
    con.commit()
    st = scope.scope_state(con)                                     # 首次读取 → 归一 + repaired=True
    assert st["all"] is True and st["repaired"] is True and st["empty"] is False
    assert "未选择" not in st["label"]
    assert scope.get_book_scope(con) is None                        # 归一为全部
    assert con.execute("SELECT COUNT(*) FROM prefs WHERE key='book_scope'").fetchone()[0] == 0  # 脏行被删

    scope.set_book_scope(con, None)
    con.commit()
    assert scope.get_book_scope(con) is None                        # 删除 key 恢复全部

    assert scope.book_filter(None, "b.id") == ("", [])
    assert scope.book_filter([], "b.id") == (" AND 0", [])
    assert scope.book_filter([1, 2], "b.id") == (" AND b.id IN (?,?)", [1, 2])
    con.close()


def test_scope_affects_queue_task_quiz(tmp_path):
    con = _seed(tmp_path)

    # SCOPE-002：选书 1 → 队列/任务/出题池只含书 1 的卡
    q1 = queue.today_queue(con, book_ids=[1])
    assert q1["new"] and all(c["book"] == "书A" for c in q1["new"])
    assert tasks.today_task(con, book_ids=[1])["review"]["target"] == 3
    assert all(c["book"] == "书A" for c in quiz._quiz_pool(con, book_ids=[1]))

    # 空范围 → 队列空 / 目标 0 + 原因 / 出题池空
    q0 = queue.today_queue(con, book_ids=[])
    assert q0["due"] == [] and q0["new"] == []
    r0 = tasks.today_task(con, book_ids=[])["review"]
    assert r0["target"] == 0 and r0["reason"]
    assert quiz._quiz_pool(con, book_ids=[]) == []

    # 全量 → 两书都在
    qa = queue.today_queue(con, book_ids=None)
    assert {c["book"] for c in qa["new"]} == {"书A", "书B"}
    con.close()


def test_scope_persists_across_reopen(tmp_path):
    """SCOPE-001：范围持久化——关闭重开连接后读回一致（重启不丢）。"""
    db = str(tmp_path / "scope.sqlite3")
    con = _seed(tmp_path)
    scope.set_book_scope(con, [2])
    con.commit()
    con.close()

    con2 = ingest_kb.connect(db)
    assert scope.get_book_scope(con2) == [2]
    assert scope.scope_state(con2)["label"] == "图书：1/2 本（书B）"
    con2.close()


def test_scope_does_not_mutate_cards(tmp_path):
    """SCOPE-002：范围只读——设范围前后卡 status/next_review_at/learn_count 逐字段不变（不吃卡/不改期/不丢卡）。"""
    con = _seed(tmp_path)
    def snap():
        return [dict(r) for r in con.execute(
            "SELECT id, status, next_review_at, learn_count FROM cards ORDER BY id").fetchall()]
    before = snap()
    scope.set_book_scope(con, [1])
    con.commit()
    scope.set_book_scope(con, [])
    con.commit()
    queue.today_queue(con, book_ids=[1])
    tasks.today_task(con, book_ids=[1])
    scope.set_book_scope(con, None)
    con.commit()
    assert snap() == before
    con.close()


def test_scope_api_validation(tmp_path, monkeypatch):
    """PUT /api/scope：all 与 book_ids 两态、非法 id / 非数组拒绝；[] 拒绝（SCOPE-003 修订）。"""
    db = tmp_path / "api.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('psy','psychology',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'书','book','active','t')")
    con.commit()
    con.close()

    from app import create_app
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        d = c.get("/api/scope").get_json()["data"]
        assert d["all"] is True and d["label"] == "图书：全部"

        r = c.put("/api/scope", json={"book_ids": [1]})
        d = r.get_json()["data"]
        assert d["all"] is False and d["selected_ids"] == [1]
        assert d["label"] == "图书：1/1 本（书）"

        r = c.put("/api/scope", json={"book_ids": []})
        assert r.get_json()["code"] != 0 and "至少选择一本书" in r.get_json()["msg"]

        r = c.put("/api/scope", json={"all": True})
        assert r.get_json()["data"]["all"] is True

        assert c.put("/api/scope", json={"book_ids": [999]}).get_json()["code"] != 0
        assert c.put("/api/scope", json={"book_ids": "1"}).get_json()["code"] != 0
        assert c.put("/api/scope", json={}).get_json()["code"] != 0


def test_scope_rejects_empty_scope(tmp_path, monkeypatch):
    """D1：PUT {book_ids:[]} → 非 0 code + msg 含「至少选择一本书」，且 prefs 行未变。"""
    db = tmp_path / "reject.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('psy','psychology',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'书','book','active','t')")
    con.commit()
    con.close()

    from app import create_app
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.put("/api/scope", json={"book_ids": [1]})
        con2 = ingest_kb.connect(str(db))
        before = con2.execute("SELECT value FROM prefs WHERE key='book_scope'").fetchone()
        con2.close()

        r = c.put("/api/scope", json={"book_ids": []})
        assert r.get_json()["code"] != 0
        assert "至少选择一本书" in r.get_json()["msg"]

        con3 = ingest_kb.connect(str(db))
        after = con3.execute("SELECT value FROM prefs WHERE key='book_scope'").fetchone()
        con3.close()
        assert (before["value"] if before else None) == (after["value"] if after else None)  # 未变


def test_scope_normalizes_empty_on_read(tmp_path, monkeypatch):
    """D3：预置 prefs.book_scope="[]"（迁移之后）→ GET /api/scope 的 all==True、repaired==True，且 pref 行被删。"""
    db = tmp_path / "normalize.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('psy','psychology',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'书','book','active','t')")
    con.commit()
    con.close()

    from app import create_app
    app = create_app("development")           # 启动迁移先跑（此时无 "[]" 行）
    app.config["TESTING"] = True
    with app.test_client() as c:
        # 迁移之后再预置脏行 → 触发「读取时归一」路径（运行时兜底，repaired=True）
        con2 = ingest_kb.connect(str(db))
        con2.execute("INSERT INTO prefs(user_id,key,value) VALUES(1,'book_scope','[]')")
        con2.commit()
        con2.close()

        d = c.get("/api/scope").get_json()["data"]
        assert d["all"] is True and d["repaired"] is True
        assert "未选择" not in d["label"]

        con3 = ingest_kb.connect(str(db))
        row = con3.execute("SELECT value FROM prefs WHERE key='book_scope'").fetchone()
        con3.close()
        assert row is None  # 脏行被删/归一


def test_scope_migration_deletes_empty_pref(tmp_path):
    """A5：幂等迁移删除 prefs.book_scope="[]" 脏行（启动即清）。"""
    db = tmp_path / "migrate.sqlite3"
    con = ingest_kb.connect(str(db))
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at) VALUES('psy','psychology',0,'t')")
    con.execute("INSERT INTO books(owner_id,subject_id,title,slug,status,created_at) VALUES(1,1,'书','book','active','t')")
    con.execute("INSERT INTO prefs(user_id,key,value) VALUES(1,'book_scope','[]')")
    con.commit()
    con.close()

    # 重新 connect（等价启动）触发迁移 → 脏行被删
    con2 = ingest_kb.connect(str(db))
    row = con2.execute("SELECT value FROM prefs WHERE key='book_scope'").fetchone()
    con2.close()
    assert row is None


def test_scope_label_never_unselected(tmp_path):
    """D4：任何情况下 /api/scope 的 label 不得出现子串「未选择」。"""
    con = _seed(tmp_path)
    for selected in (None, [1], [2], [1, 2]):
        scope.set_book_scope(con, selected)
        con.commit()
        label = scope.scope_state(con)["label"]
        assert "未选择" not in label, label
    con.close()
