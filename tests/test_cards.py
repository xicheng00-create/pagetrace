"""MAST-003：卡片四状态标签（后端唯一词表 `status_label`；前端零映射）。

词表唯一：`new→未学习 / learning→学习中 / review→复习中 / mastered→已掌握`；
未知 `status` → 回落「未学习」并**记 warning**（不得静默）。
"""
import logging
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402
from services import labels  # noqa: E402

from scripts import ingest_kb  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cards-contract-1.jsonl"


def test_status_label_four_states(caplog):
    assert labels.STATUS_LABELS == {
        "new": "未学习", "learning": "学习中", "reviewing": "复习中", "mastered": "已掌握",
    }
    for st, lab in labels.STATUS_LABELS.items():
        assert labels.status_label(st) == lab
    # 未知 / 空 status → 未学习 + 记 warning（不得静默）
    with caplog.at_level(logging.WARNING, logger="services.labels"):
        assert labels.status_label("weird") == "未学习"
        assert labels.status_label(None) == "未学习"
    assert sum("weird" in r.getMessage() for r in caplog.records) == 1
    assert len(caplog.records) >= 2


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "cards.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    con = ingest_kb.connect(str(db))
    ingest_kb.ingest_file(con, FIXTURE)
    con.close()
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _cards(client, cid):
    return client.get(f"/api/cards?concept_id={cid}").get_json()["data"]["cards"]


def test_cards_response_carries_status_label(client):
    cid = client.get("/api/concepts?chapter_id=1").get_json()["data"]["concepts"][0]["id"]
    cards = _cards(client, cid)
    assert cards and all(c["status_label"] == "未学习" for c in cards)  # 新入库 → new
    # 改一张为 review → 标签随状态机变化（后端单点算）
    with client.application.app_context():
        from data.db import get_db
        get_db().execute("UPDATE cards SET status='reviewing' WHERE id=?", (cards[0]["id"],))
        get_db().commit()
    by_id = {c["id"]: c["status_label"] for c in _cards(client, cid)}
    assert by_id[cards[0]["id"]] == "复习中"


def test_today_and_plan_carry_status_label(client):
    today = client.get("/api/today?extra=1").get_json()["data"]
    assert today["new"] and all(c["status_label"] == "未学习" for c in today["new"])
    # extra=1 与默认同口径（「再来一组」不改队列规则）
    plain = client.get("/api/today").get_json()["data"]
    assert [c["card_id"] for c in today["new"]] == [c["card_id"] for c in plain["new"]]


# —— CARD-007 / UI-019：契约 title 落库 + 子卡短名（后端派生，前端零 split） ——

def test_subtitle_of_derivation():
    assert labels.subtitle_of("I立方模型 · 激发因素", "I立方模型") == "激发因素"
    assert labels.subtitle_of("心智层级 · 技能树高度取各线均值", "心智层级") == "技能树高度取各线均值"
    assert labels.subtitle_of("冲煮变量 · 冲煮变量", "冲煮变量") is None   # 右段 == 概念名 → 不显示
    assert labels.subtitle_of("预热步骤", "预热步骤") is None             # 未切分卡
    assert labels.subtitle_of("四种冲煮变量", "冲煮变量") == "四种冲煮变量"  # 老式标题（无分隔符）
    assert labels.subtitle_of("A · B · C", "A") == "C"                    # 取最后一段
    assert labels.subtitle_of("", "X") is None and labels.subtitle_of(None, None) is None


def test_cards_carry_title_and_subtitle(client):
    data = client.get("/api/cards?concept_id=1").get_json()["data"]
    assert data["concept_name"] == "冲煮变量"
    assert data["cards"][0]["title"] == "四种冲煮变量"      # 契约 title 逐字入库
    assert data["cards"][0]["subtitle"] == "四种冲煮变量"


def test_unsplit_card_subtitle_is_none(client):
    """未切分卡（title == 概念名）→ subtitle=None：卡面不出现「合成示例书10 · 合成示例书10」。"""
    data = client.get("/api/cards?concept_id=2").get_json()["data"]
    assert data["concept_name"] == "预热步骤"
    assert data["cards"][0]["title"] == "预热步骤"
    assert data["cards"][0]["subtitle"] is None


def test_today_and_plan_carry_subtitle(client):
    today = client.get("/api/today?extra=1").get_json()["data"]
    assert today["new"] and all("subtitle" in c for c in today["new"])
    with client.application.app_context():
        from data.db import get_db
        get_db().execute("UPDATE cards SET status='learning'")
        get_db().commit()
    items = client.get("/api/plan").get_json()["data"]["items"]
    assert items and all("title" in x and "subtitle" in x for x in items)
