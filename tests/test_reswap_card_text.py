"""Reswap safety tests use temporary fixture databases only."""
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
from scripts.ingest_store import content_hash  # noqa: E402

from scripts import ingest_kb, reswap_card_text  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "cards-contract-1.jsonl"


def _db(tmp_path):
    path = tmp_path / "reswap.sqlite3"
    con = ingest_kb.connect(str(path))
    ingest_kb.ingest_file(con, FIXTURE)
    con.execute("UPDATE cards SET status='reviewing', learn_count=3, next_review_at='2026-01-01', created_at='created'")
    con.commit()
    con.close()
    return path


def _source(tmp_path, db_path, mutate=None):
    con = sqlite3.connect(db_path)
    rows = []
    for row in con.execute("SELECT cp.concept_uid, c.front, c.back FROM cards c JOIN concepts cp ON cp.id=c.concept_id ORDER BY cp.concept_uid,c.id"):
        rows.append({"concept_id": row[0], "question": row[1], "answer_points": row[2].split("\n")})
    con.close()
    if mutate:
        mutate(rows)
    path = tmp_path / "source.jsonl"
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf8")
    return path


def _book(db):
    con = sqlite3.connect(db)
    title = con.execute("SELECT title FROM books LIMIT 1").fetchone()[0]
    con.close()
    return title


def test_rejects_count_mismatch_without_mutation(tmp_path, capsys):
    db = _db(tmp_path)
    source = _source(tmp_path, db, lambda rows: rows.pop())
    assert reswap_card_text.main(["--db", str(db), "--book", _book(db), "--source", str(source)]) != 0
    assert "row counts differ" in capsys.readouterr().err
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 3
    con.close()


def test_apply_preserves_progress_hash_and_is_idempotent(tmp_path, capsys):
    db = _db(tmp_path)
    source = _source(tmp_path, db, lambda rows: rows[0].update(question="English front", answer_points=["English back"]))
    args = ["--db", str(db), "--book", _book(db), "--source", str(source), "--apply"]
    assert reswap_card_text.main(args) == 0
    con = sqlite3.connect(db)
    row = con.execute("SELECT id,concept_id,learn_count,status,next_review_at,created_at,front,back,content_hash FROM cards ORDER BY id LIMIT 1").fetchone()
    con.close()
    assert row[:6] == (1, 1, 3, "reviewing", "2026-01-01", "created")
    assert row[8] == content_hash(row[6], row[7])
    reswap_card_text.main(args)
    assert "changed=0 unchanged=2" in capsys.readouterr().out


# —— CARD-008：上游换版时就地采纳新题面，保住卡 id 与复习进度 ——


def test_back_mode_adopts_rewritten_front_and_preserves_progress(tmp_path, capsys):
    """背面逐字相同、仅题面被上游重写 → 按知识点配对，卡 id / 进度 / 历史不动。"""
    db = _db(tmp_path)
    source = _source(tmp_path, db, lambda rows: [r.update(question="改写后的题面") for r in rows])
    args = ["--db", str(db), "--book", _book(db), "--source", str(source), "--match", "back", "--apply"]
    assert reswap_card_text.main(args) == 0
    assert "changed=3 unchanged=0" in capsys.readouterr().out
    con = sqlite3.connect(db)
    rows = con.execute("SELECT id,front,back,learn_count,status,next_review_at,content_hash"
                       " FROM cards ORDER BY id").fetchall()
    con.close()
    assert [r[0] for r in rows] == [1, 2, 3]                  # 卡 id 未变（不是「删了重插」）
    assert {r[1] for r in rows} == {"改写后的题面"}             # 题面 = 新版文本
    assert {r[3] for r in rows} == {3}                        # learn_count 保住
    assert {r[4] for r in rows} == {"reviewing"}              # status 保住
    assert {r[5] for r in rows} == {"2026-01-01"}             # next_review_at 保住
    assert all(r[6] == content_hash(r[1], r[2]) for r in rows)  # hash 与卡文同源
    assert reswap_card_text.main(args) == 0
    assert "changed=0 unchanged=3" in capsys.readouterr().out   # 幂等


def test_back_mode_counts_rows_without_counterpart_as_new(tmp_path, capsys):
    """库内没有同正文的卡 = 上游新增 → 跳过并计数（由 ingest 新增），不是失败。"""
    db = _db(tmp_path)
    source = _source(tmp_path, db)
    extra = json.loads(source.read_text(encoding="utf8").splitlines()[0])
    extra = {**extra, "question": "上游新增的题面", "answer_points": ["上游新增的正文"]}
    source.write_text(source.read_text(encoding="utf8") + json.dumps(extra, ensure_ascii=False) + "\n",
                      encoding="utf8")
    cmd = ["--db", str(db), "--book", _book(db), "--source", str(source), "--match", "back"]
    assert reswap_card_text.main(cmd) == 0
    out = capsys.readouterr().out
    assert "changed=0 unchanged=3" in out
    assert "new_rows=1" in out and "unmatched_db=0" in out


def test_back_mode_rejects_when_pairing_is_not_unique(tmp_path, capsys):
    """同一 concept 内背面命中 2 张（撞车）→ 整批拒绝且库零改动（不猜、不近似配）。"""
    db = _db(tmp_path)
    con = sqlite3.connect(db)
    r = con.execute("SELECT concept_id, subject_id, back, source FROM cards ORDER BY id LIMIT 1").fetchone()
    dup_front = "库里另一张同正文的卡"
    con.execute("INSERT INTO cards(concept_id, subject_id, front, back, source, content_hash, status, created_at)"
                " VALUES(?,?,?,?,?,?,'new','t')",
                (r[0], r[1], dup_front, r[2], r[3], content_hash(dup_front, r[2])))
    con.commit()
    con.close()
    source = _source(tmp_path, db)
    cmd = ["--db", str(db), "--book", _book(db), "--source", str(source), "--match", "back"]
    assert reswap_card_text.main(cmd) != 0
    assert "背面唯一配对失败" in capsys.readouterr().err
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 4
    assert con.execute("SELECT COUNT(*) FROM cards WHERE front=?", ("改写后的题面",)).fetchone()[0] == 0
    con.close()
