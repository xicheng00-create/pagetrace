"""CARD-006 ingest smoke: similar cards survive and exact duplicates stay idempotent."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from scripts import ingest_kb  # noqa: E402


def test_similar_batch_and_idempotent(tmp_path):
    rows = []
    for i in range(20):
        rows.append({"contract": 1, "concept_id": f"c{i}", "subject": "s", "book": "b", "chapter": "第1章",
                     "title": f"t{i}", "question": f"同页概念{i}是什么？", "answer_points": [f"答案{i}"]})
    path = tmp_path / "sample.jsonl"
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
    con = ingest_kb.connect(str(tmp_path / "db.sqlite3"))
    first = ingest_kb.ingest_file(con, path)
    second = ingest_kb.ingest_file(con, path)
    assert (first["new"], first["merged"], first["rejected"]) == (20, 0, 0)
    assert (second["new"], second["skipped"]) == (0, 20)
    con.close()
