"""DATA-006: chapter display names and card sources, using only temporary databases."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from scripts import ingest_kb  # noqa: E402


def _row(uid, chapter="ch-L001", **extra):
    return {"contract": 1, "concept_id": uid, "subject": "creator", "book": "合成示例书5",
            "chapter": chapter, "title": uid, "question": f"{uid}是什么？",
            "answer_points": [f"{uid}答案"], **extra}


def _file(tmp_path, rows):
    path = tmp_path / "cards.jsonl"
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n",
                    encoding="utf-8")
    return path


def _snapshot(con):
    chapters = [tuple(r) for r in con.execute("SELECT anchor, name FROM chapters ORDER BY anchor")]
    cards = [tuple(r) for r in con.execute("SELECT source FROM cards ORDER BY id")]
    return chapters, cards


def test_chapter_title_and_missing_title_idempotent(tmp_path):
    con = ingest_kb.connect(str(tmp_path / "test.db"))
    path = _file(tmp_path, [_row("A", chapter_title="自助不等于自我提升"),
                            _row("B", "ch-L002")])
    first = ingest_kb.ingest_file(con, path)
    before = _snapshot(con)
    assert before == ([("ch-L001", "ch-L001 · 自助不等于自我提升"),
                       ("ch-L002", "ch-L002")],
                      [("合成示例书5/ch-L001 · 自助不等于自我提升",),
                       ("合成示例书5/ch-L002",)])
    second = ingest_kb.ingest_file(con, path)
    assert first["new"] == 2 and second["new"] == 0 and second["skipped"] == 2
    assert _snapshot(con) == before
    con.close()


def test_existing_manual_name_and_source_preserved_then_refreshed(tmp_path):
    con = ingest_kb.connect(str(tmp_path / "test.db"))
    path = _file(tmp_path, [_row("A")])
    ingest_kb.ingest_file(con, path)
    con.execute("UPDATE chapters SET name='ch-L001 · 自助不等于自我提升'")
    con.execute("UPDATE cards SET source='old/source'")
    dry = ingest_kb.ingest_file(con, path, dry_run=True)
    assert (dry["new"], dry["skipped"]) == (0, 1)
    assert con.execute("SELECT source FROM cards").fetchone()[0] == "old/source"
    again = ingest_kb.ingest_file(con, path)
    assert (again["new"], again["skipped"]) == (0, 1)
    assert _snapshot(con) == ([("ch-L001", "ch-L001 · 自助不等于自我提升")],
                              [("合成示例书5/ch-L001 · 自助不等于自我提升",)])
    con.close()


def test_invalid_chapter_titles_rejected_without_writes(tmp_path):
    con = ingest_kb.connect(str(tmp_path / "test.db"))
    rows = [_row("good", chapter_title="标题"), _row("long", chapter_title="字" * 41),
            _row("numeric", chapter_title=123), _row("newline", chapter_title="甲\n乙"),
            _row("return", chapter_title="甲\r乙")]
    result = ingest_kb.ingest_file(con, _file(tmp_path, rows))
    assert (result["new"], result["rejected"]) == (1, 4)
    assert all("chapter_title" in reason for reason in result["reasons"])
    assert con.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 1
    con.close()


def test_title_updates_existing_chapter_and_card_source_with_pages(tmp_path):
    con = ingest_kb.connect(str(tmp_path / "test.db"))
    path = _file(tmp_path, [_row("A", pages=[12, 13])])
    ingest_kb.ingest_file(con, path)
    _file(tmp_path, [_row("A", pages=[12, 13], chapter_title="新章标题")])
    stats = ingest_kb.ingest_file(con, path)
    assert (stats["new"], stats["skipped"]) == (0, 1)
    assert _snapshot(con) == ([("ch-L001", "ch-L001 · 新章标题")],
                              [("合成示例书5/ch-L001 · 新章标题/12,13",)])
    con.close()
