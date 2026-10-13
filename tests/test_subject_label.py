"""0.5.1（DATA-006）：学科显示名的唯一来源 = 库内 subjects.name。

反向断言（本 bug 的机械特征与防回归）：
1. ingest 重跑**不得**把已改好的显示名冲回 slug（幂等且不覆盖）。
2. 映射未命中 → 回落 slug **且**产生一条 warning（caplog 断言）。
3. `/api/subjects` 返回的 `name` 与 `slug` **不再相同**（slug 直出就是本 bug）。
4. 回填幂等：映射里没有的 slug 一动不动；第二次跑变更 0 行。
"""
import json
import logging
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import create_app  # noqa: E402
from config import BaseConfig  # noqa: E402
from scripts.ingest_store import backfill_subject_labels, connect, subject_label  # noqa: E402

from scripts import backfill_subject_labels as backfill_cli  # noqa: E402
from scripts import ingest_kb  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LABEL = BaseConfig.SUBJECT_LABELS["psychology"]  # 心理学


def _con(tmp_path, name="t.sqlite3"):
    return connect(str(tmp_path / name))


def _names(con):
    return {r["slug"]: r["name"] for r in con.execute("SELECT slug, name FROM subjects")}


def test_mapping_and_label_lookup():
    assert subject_label("psychology") == LABEL
    assert subject_label("nope") is None  # 未映射 → None（由调用方回落 + warning）


def test_new_subject_uses_label_not_slug(tmp_path):
    con = _con(tmp_path)
    ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    assert _names(con) == {"psychology": LABEL}
    con.close()


def test_reingest_keeps_label(tmp_path):
    """反向断言①a：重跑幂等 —— 显示名仍是映射名，不被冲回 slug。"""
    con = _con(tmp_path)
    ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    second = ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    assert second["new"] == 0 and second["skipped"] == 3
    assert _names(con) == {"psychology": LABEL}
    con.close()


def test_reingest_does_not_overwrite_manual_name(tmp_path):
    """反向断言①b：既有学科的 name 一律不碰 —— 手工改过的值也不许被 ingest 冲掉。"""
    con = _con(tmp_path)
    ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    con.execute("UPDATE subjects SET name='我改的名字' WHERE slug='psychology'")
    con.commit()
    ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    assert _names(con) == {"psychology": "我改的名字"}
    con.close()


def test_unmapped_subject_falls_back_to_slug_with_warning(tmp_path, caplog):
    """反向断言②：未映射 → name = slug + 一条 warning（不静默）。"""
    f = tmp_path / "unknown.jsonl"
    f.write_text(json.dumps({
        "contract": 1, "concept_id": "x", "subject": "philosophy", "book": "b",
        "chapter": "第1章", "title": "t", "question": "q?", "answer_points": ["a"],
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    con = _con(tmp_path)
    with caplog.at_level(logging.WARNING):
        ingest_kb.ingest_file(con, f)
    assert _names(con) == {"philosophy": "philosophy"}  # 回落 slug
    warns = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("philosophy" in w and "无显示名映射" in w for w in warns), caplog.text
    con.close()


def test_existing_subject_no_warning(tmp_path, caplog):
    """已映射学科走新建路径不该产生 warning（warning 只属于「未映射」）。"""
    con = _con(tmp_path)
    with caplog.at_level(logging.WARNING):
        ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
    con.close()


def test_api_subjects_name_differs_from_slug(tmp_path, monkeypatch):
    """反向断言③：接口返回的 name 与 slug 不再相同（slug 直出正是本 bug 的机械特征）。"""
    db = tmp_path / "api.sqlite3"
    con = connect(str(db))
    ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    con.close()
    monkeypatch.setenv("DATABASE_PATH", str(db))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        subs = c.get("/api/subjects").get_json()["data"]["subjects"]
    assert [s["slug"] for s in subs] == ["psychology"]
    assert [s["name"] for s in subs] == [LABEL]
    assert subs[0]["name"] != subs[0]["slug"], "name == slug 即显示名未生效"


def test_backfill_updates_only_mapped_and_is_idempotent(tmp_path):
    """反向断言④：回填只动映射命中的行，未命中的一动不动；第二次跑变更 0 行。"""
    con = _con(tmp_path)
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at)"
                " VALUES('psychology','psychology',0,'t')")          # 命中，需回填
    con.execute("INSERT INTO subjects(name,slug,order_no,created_at)"
                " VALUES('哲学','philosophy',1,'t')")                # 未命中，name 不动
    con.commit()
    rows = backfill_subject_labels(con)
    con.commit()
    assert _names(con) == {"psychology": LABEL, "philosophy": "哲学"}
    assert sum(1 for r in rows if r["changed"]) == 1
    # 幂等：再跑一次，零变更
    again = backfill_subject_labels(con)
    assert sum(1 for r in again if r["changed"]) == 0
    assert _names(con) == {"psychology": LABEL, "philosophy": "哲学"}
    con.close()


def test_backfill_cli_dry_run_writes_nothing(tmp_path, capsys):
    db = tmp_path / "dry.sqlite3"
    con = connect(str(db))
    ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    con.execute("UPDATE subjects SET name='psychology' WHERE slug='psychology'")
    con.commit()
    con.close()
    assert backfill_cli.main(["--db", str(db), "--dry-run"]) == 0
    assert "dry-run" in capsys.readouterr().out
    con = connect(str(db))
    assert _names(con) == {"psychology": "psychology"}  # 未写库
    con.close()


def test_backfill_cli_backs_up_then_updates(tmp_path, monkeypatch, capsys):
    """改数据前必须先落带时间戳的备份（铁律），并打印 before/after 账。"""
    db = tmp_path / "real.sqlite3"
    con = connect(str(db))
    ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    con.execute("UPDATE subjects SET name='psychology' WHERE slug='psychology'")
    con.commit()
    con.close()
    monkeypatch.setattr(backfill_cli, "REPO_ROOT", tmp_path)
    assert backfill_cli.main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    backups = list((tmp_path / "backups").glob("review-*-pre-subject-labels.sqlite3"))
    assert len(backups) == 1, "必须落一份带时间戳的备份"
    assert "备份：" in out and "psychology" in out and LABEL in out
    con = connect(str(db))
    assert _names(con) == {"psychology": LABEL}
    con.close()


def test_backfill_cli_missing_db(tmp_path, capsys):
    assert backfill_cli.main(["--db", str(tmp_path / "nope.sqlite3")]) == 1
    assert "无库文件" in capsys.readouterr().out


@pytest.mark.parametrize("slug", ["psychology"])
def test_label_map_is_str_to_str(slug):
    labels = BaseConfig.SUBJECT_LABELS
    assert isinstance(labels, dict) and labels
    assert all(isinstance(k, str) and isinstance(v, str) and v for k, v in labels.items())
