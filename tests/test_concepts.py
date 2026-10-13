"""MAST-005（v0.6.1）：概念下发卡状态 —— `status_counts`（恒四键）+ `status_label`。

口径（DESIGN_SPEC §3.8 MAST-005）：**同态** → 该态中文标签；**多态** → `未学习 2 · 学习中 1`
（顺序固定 新→学→复→掌、只列非零）；**无卡** → 「无卡」；未知 `status` → 计入 `new` + 顶层 `warnings`
（并记 log，不得静默吞）。词表唯一来源 = `config.BaseConfig.STATUS_LABELS`，前端零映射零拼接。
"""
import logging
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402
from config import BaseConfig  # noqa: E402
from services import labels  # noqa: E402

from scripts import ingest_kb  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cards-contract-1.jsonl"
ZERO = {"new": 0, "learning": 0, "reviewing": 0, "mastered": 0}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "concepts.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    ingest_kb.ingest_file(con, FIXTURE)
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _data(client, chid=1):
    return client.get(f"/api/concepts?chapter_id={chid}").get_json()["data"]


def _by_name(data):
    return {c["name"]: c for c in data["concepts"]}


def _card(client, concept_id, status, tag):
    """建一张卡（只在测试临时库写；生产验收零写入）。"""
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        sid = con.execute("SELECT subject_id FROM cards WHERE concept_id=?",
                          (concept_id,)).fetchone()[0]
        con.execute(
            "INSERT INTO cards (concept_id, subject_id, front, back, source, content_hash,"
            " status, learn_count, created_at) VALUES (?,?,?,?,?,?,?,0,?)",
            (concept_id, sid, f"q-{tag}", "a", "manual", f"hash-{tag}", status,
             "2026-09-27T00:00:00+08:00"))
        con.commit()


def _concept_id(client, name):
    with client.application.app_context():
        from data.db import get_db
        return get_db().execute(
            "SELECT id FROM concepts WHERE name=?", (name,)).fetchone()[0]


def _set_all(client, concept_id, status):
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        con.execute("UPDATE cards SET status=? WHERE concept_id=?", (status, concept_id))
        con.commit()


def test_word_table_single_source():
    """四态中文词表唯一来源 = `config`（MAST-005 铁律：前端零映射、零拼接）。"""
    assert labels.STATUS_LABELS is BaseConfig.STATUS_LABELS
    assert BaseConfig.STATUS_LABELS == {
        "new": "未学习", "learning": "学习中", "reviewing": "复习中", "mastered": "已掌握"}
    assert list(BaseConfig.STATUS_ORDER) == ["new", "learning", "reviewing", "mastered"]
    assert BaseConfig.STATUS_UNKNOWN_LABEL == "未学习"
    assert BaseConfig.STATUS_NO_CARD_LABEL == "无卡"


def test_status_counts_and_label(client, caplog):
    # ① 建库态：两个概念各 1 张 new 卡 → 恒四键 + 同态标签
    d = _data(client)
    assert d["locked"] is False and d["warnings"] == []
    names = _by_name(d)
    assert sorted(names) == ["冲煮变量", "预热步骤"]
    assert names["冲煮变量"]["status_counts"] == {**ZERO, "new": 1}
    assert names["冲煮变量"]["status_label"] == "未学习"

    # ② 四态分布 → 计数正确 + 多态标签（顺序 新→学→复→掌、只列非零）
    cid = _concept_id(client, "冲煮变量")
    for st in ("learning", "reviewing", "mastered"):
        _card(client, cid, st, f"{cid}-{st}")
    c1 = _by_name(_data(client))["冲煮变量"]
    assert c1["cards_total"] == 4
    assert c1["status_counts"] == {"new": 1, "learning": 1, "reviewing": 1, "mastered": 1}
    assert c1["status_label"] == "未学习 1 · 学习中 1 · 复习中 1 · 已掌握 1"

    # ③ 多态只列非零、顺序固定：2 new + 1 learning → `未学习 2 · 学习中 1`
    cid2 = _concept_id(client, "预热步骤")
    _card(client, cid2, "new", f"{cid2}-new")
    _card(client, cid2, "learning", f"{cid2}-learning")
    c2 = _by_name(_data(client))["预热步骤"]
    assert c2["status_counts"] == {"new": 2, "learning": 1, "reviewing": 0, "mastered": 0}
    assert c2["status_label"] == "未学习 2 · 学习中 1"

    # ④ 全部同态 → 该态标签（单态不带计数）
    _set_all(client, cid, "mastered")
    c1 = _by_name(_data(client))["冲煮变量"]
    assert c1["status_counts"] == {**ZERO, "mastered": 4}
    assert c1["status_label"] == "已掌握"

    # ⑤ 无卡 → 「无卡」+ 恒四键全 0
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        con.execute("INSERT INTO concepts (concept_uid, chapter_id, name) VALUES (?,?,?)",
                    ("empty-concept", 1, "空概念"))
        con.commit()
    empty = _by_name(_data(client))["空概念"]
    assert empty["cards_total"] == 0
    assert empty["status_counts"] == ZERO and empty["status_label"] == "无卡"

    # 未知状态无法通过数据库 CHECK；函数级验证标签回落并记录 warning。
    from services.labels import status_label
    with caplog.at_level(logging.WARNING):
        assert status_label("weird") == "未学习"
    assert any("weird" in r.getMessage() for r in caplog.records)

    locked = _data(client, chid=2)
    assert locked["locked"] is True and locked["concepts"] == []
