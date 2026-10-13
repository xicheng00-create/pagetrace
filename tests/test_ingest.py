"""段③ ingest：契约校验 / 幂等 / 违规拒绝 / 解锁首章 / 审计。

跑法：.venv/bin/pytest -q tests/test_ingest.py
"""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from scripts import ingest_kb  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _con(tmp_path):
    return ingest_kb.connect(str(tmp_path / "t.sqlite3"))


def _counts(con):
    return {
        "cards": con.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
        "subjects": con.execute("SELECT COUNT(*) FROM subjects").fetchone()[0],
        "books": con.execute("SELECT COUNT(*) FROM books").fetchone()[0],
        "chapters": con.execute("SELECT COUNT(*) FROM chapters").fetchone()[0],
    }


def test_valid_lines_ingested_and_invalid_rejected(tmp_path):
    con = _con(tmp_path)
    stats = ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    assert stats["new"] == 3
    assert stats["rejected"] == 1  # 缺 answer_points 的那行
    assert any("answer_points" in r for r in stats["reasons"])
    assert _counts(con)["cards"] == 3
    con.close()


def test_pages_interval_string_accepted(tmp_path):
    con = _con(tmp_path)
    ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    row = con.execute("SELECT source_pages FROM concepts WHERE concept_uid='预热步骤'").fetchone()
    assert row["source_pages"] == "12-13"
    con.close()


def test_ingest_idempotent(tmp_path):
    """幂等自证：同一文件连跑两次，第二次「新增 0 / 跳过 3」。"""
    con = _con(tmp_path)
    first = ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    second = ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    assert first["new"] == 3
    assert second["new"] == 0
    assert second["skipped"] == 3
    assert _counts(con)["cards"] == 3  # 库不膨胀
    con.close()


def test_contract2_whole_file_rejected(tmp_path):
    con = _con(tmp_path)
    stats = ingest_kb.ingest_file(con, FIXTURES / "cards-contract-2.jsonl")
    assert stats["contract_ok"] is False
    assert stats["new"] == 0
    assert stats["rejected"] == 1
    assert _counts(con)["cards"] == 0
    con.close()


def test_missing_answer_points_rejected_and_db_unchanged(tmp_path):
    """反向断言：删掉某行 answer_points → 该行被拒且库不变。"""
    src = (FIXTURES / "cards-contract-1.jsonl").read_text(encoding="utf-8").splitlines()
    good = FIXTURES / "cards-contract-1.jsonl"
    broken = tmp_path / "broken.jsonl"
    lines = []
    for ln in src:
        o = json.loads(ln)
        if o["concept_id"] == "预热步骤":
            o.pop("answer_points", None)  # 删掉一行必填字段
        lines.append(json.dumps(o, ensure_ascii=False))
    broken.write_text("\n".join(lines) + "\n", encoding="utf-8")

    con = _con(tmp_path)
    before = ingest_kb.ingest_file(con, good)
    assert before["new"] == 3
    after = ingest_kb.ingest_file(con, broken)
    assert after["rejected"] == 2  # fixture 自带 1 + 新删 1
    assert after["new"] == 0 and after["skipped"] == 2
    assert _counts(con)["cards"] == 3  # 库不变
    con.close()


def test_new_book_unlocks_first_chapter(tmp_path):
    """SCHED-001：新书入库即解锁其第 1 章。"""
    con = _con(tmp_path)
    ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    rows = con.execute("SELECT anchor, unlocked_at FROM chapters ORDER BY order_no").fetchall()
    assert rows[0]["anchor"] == "第1章" and rows[0]["unlocked_at"]
    # 未达阈值的第 2 章仍上锁
    assert rows[1]["anchor"] == "第2章" and rows[1]["unlocked_at"] is None
    con.close()


def test_title_stored_and_idempotent_backfill(tmp_path):
    """CARD-007：契约 `title`（「概念名 · 子卡短名」）逐字落库；旧行由幂等重导回填，再跑回填 0。"""
    con = _con(tmp_path)
    ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    got = {r["concept_uid"]: r["title"] for r in con.execute(
        "SELECT cp.concept_uid AS concept_uid, c.title FROM cards c"
        " JOIN concepts cp ON cp.id = c.concept_id")}
    assert got == {"冲煮变量": "四种冲煮变量", "预热步骤": "预热步骤", "注水节奏": "注水节奏策略"}

    con.execute("UPDATE cards SET title=NULL")  # 模拟加列前的旧库
    stats = ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    assert stats["new"] == 0 and stats["backfilled"] == 3
    assert con.execute("SELECT COUNT(*) FROM cards WHERE title IS NULL").fetchone()[0] == 0
    again = ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    assert again["backfilled"] == 0 and again["skipped"] == 3  # 回填也幂等
    con.close()


def test_write_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_kb, "REPO_ROOT", tmp_path)
    con = _con(tmp_path)
    stats = ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl")
    path = ingest_kb.write_audit([stats], "2026-09-26T10:00:00+08:00")
    assert path.exists() and "ingest 审计" in path.read_text(encoding="utf-8")
    assert "待人工" in path.read_text(encoding="utf-8")
    con.close()


def test_collect_files_and_connect(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    (exports / "psychology").mkdir(parents=True)
    f = exports / "psychology" / "book.jsonl"
    f.write_text("{}\n", encoding="utf-8")
    assert ingest_kb._collect_files(exports, None, None, None) == [f]
    assert ingest_kb._collect_files(exports, "psychology", "book", None) == [f]
    assert ingest_kb._collect_files(exports, "nope", None, None) == []
    assert ingest_kb._collect_files(exports, None, None, str(f)) == [f]
    con = ingest_kb.connect(str(tmp_path / "x.sqlite3"))
    assert con.execute("SELECT 1").fetchone()[0] == 1
    con.close()
    assert ingest_kb.resolve_db_path()


def test_dry_run_writes_nothing(tmp_path):
    con = _con(tmp_path)
    stats = ingest_kb.ingest_file(con, FIXTURES / "cards-contract-1.jsonl", dry_run=True)
    assert stats["new"] == 3  # 预估
    assert _counts(con)["cards"] == 0
    con.close()


def test_no_files_returns_empty(tmp_path):
    con = _con(tmp_path)
    assert ingest_kb.scan_kb(con, tmp_path / "empty", dry_run=True) == []
    con.close()


def test_main_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ingest_kb, "REPO_ROOT", tmp_path)
    db = tmp_path / "cli.sqlite3"
    rc = ingest_kb.main(["--file", str(FIXTURES / "cards-contract-1.jsonl"), "--db", str(db)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "新增 3" in out and "待人工 1" in out


def test_pages_optional_source_degrades(tmp_path):
    """pages 可选（KB 源为 EPUB，无真实页码）：缺 pages / 空数组都收，source 退化「书/章」；
    但给了非法类型（数字）仍拒收——可选不等于不校验。"""
    base = {
        "contract": 1, "concept_id": "冲煮变量", "subject": "psychology",
        "book": "合成示例书1", "chapter": "第1章", "title": "四种冲煮变量",
        "question": "成人依恋有哪四种？", "answer_points": ["安全型", "焦虑型", "回避型", "紊乱型"],
    }
    lines = [
        dict(base, title="四种冲煮变量", question="成人依恋有哪四种？"),  # 完全没有 pages
        dict(base, concept_id="预热步骤", title="预热步骤",
             question="什么是预热步骤？", pages=[]),                  # 空数组
        dict(base, concept_id="坏页码", title="坏页码",
             question="非法页码会被收吗？", pages=12),                  # 非法类型 → 拒收
    ]
    f = tmp_path / "epub.jsonl"
    f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
                 encoding="utf-8")
    con = _con(tmp_path)
    stats = ingest_kb.ingest_file(con, f)
    assert stats["new"] == 2
    assert stats["rejected"] == 1
    assert any("pages" in r for r in stats["reasons"])
    assert {r["source"] for r in con.execute("SELECT source FROM cards")} == {"合成示例书1/第1章"}
    assert con.execute("SELECT source_pages FROM concepts WHERE concept_uid='预热步骤'").fetchone()[0] == ""
    con.close()


def test_chapter_order_follows_number(tmp_path):
    """章序按「第N章」的数字排，不按插入序；且能幂等修正已写坏的行。"""
    from scripts.ingest_store import chapter_order

    assert chapter_order("第12章") == 12
    assert chapter_order("第1章") == 1
    assert chapter_order("附录") == 0

    rows = [
        {"contract": 1, "concept_id": "D", "subject": "s", "book": "b",
         "chapter": "第12章", "title": "d", "question": "d?", "answer_points": ["d"]},
        {"contract": 1, "concept_id": "A", "subject": "s", "book": "b",
         "chapter": "第1章", "title": "a", "question": "a?", "answer_points": ["a"]},
    ]
    f = tmp_path / "b.jsonl"
    f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
    con = _con(tmp_path)
    ingest_kb.ingest_file(con, f)
    got = {r["anchor"]: r["order_no"] for r in con.execute("SELECT anchor, order_no FROM chapters")}
    assert got == {"第12章": 12, "第1章": 1}  # 第12章先写，旧实现会给它 1
    con.execute("UPDATE chapters SET order_no=99 WHERE anchor='第12章'")
    con.commit()
    ingest_kb.ingest_file(con, f)  # 幂等修正
    assert con.execute("SELECT order_no FROM chapters WHERE anchor='第12章'").fetchone()[0] == 12
    con.close()
