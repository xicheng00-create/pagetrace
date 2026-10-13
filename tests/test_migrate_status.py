"""MAST-007 迁移可用性：`review` → `reviewing` 的脚本必须**幂等**、**默认 dry-run 不写库**、**--apply 先备份**。

本文件是「迁移脚本 0% 覆盖」的补口，也是它的机械断言：
- 断言 dry-run 一个字节都不改（先跑再查库）；
- 断言 `--apply` 生成 `.bak.*` 且迁移到位；
- 断言第二次跑 = 0 行（幂等），且不产生第二份备份。
"""
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from scripts import migrate_status_reviewing as mig  # noqa: E402


def _legacy_db(tmp_path):
    """造一个「旧词表」库副本（只含脚本会用到的两列）。"""
    path = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE cards(id INTEGER PRIMARY KEY, status TEXT)")
    con.execute("CREATE TABLE card_reviews(id INTEGER PRIMARY KEY, card_id INTEGER, status TEXT)")
    con.execute("INSERT INTO cards(id,status) VALUES(1,'review'),(2,'new')")
    con.execute("INSERT INTO card_reviews(id,card_id,status) VALUES(1,1,'review')")
    con.commit()
    con.close()
    return path


def _statuses(path, table="cards"):
    con = sqlite3.connect(path)
    rows = [r[0] for r in con.execute(f"SELECT status FROM {table} ORDER BY id")]
    con.close()
    return rows


def _patch(monkeypatch, tmp_path, path, argv):
    monkeypatch.setattr(mig, "DB", path)
    monkeypatch.setattr(mig, "ROOT", tmp_path)        # 备份目录改到临时目录，绝不碰生产 data-local/
    monkeypatch.setattr(sys, "argv", argv)


def test_missing_db_is_noop(tmp_path, monkeypatch, capsys):
    """库不存在 → 打印后正常返回（不抛异常、不建文件）。"""
    _patch(monkeypatch, tmp_path, tmp_path / "nope.sqlite3", ["migrate"])
    mig.main()
    assert "数据库不存在" in capsys.readouterr().out


def test_dry_run_does_not_write(tmp_path, monkeypatch, capsys):
    """默认（无 --apply）= 干跑：只报数，一行都不许改。"""
    path = _legacy_db(tmp_path)
    _patch(monkeypatch, tmp_path, path, ["migrate"])
    mig.main()
    out = capsys.readouterr().out
    assert "干跑：cards 1; card_reviews 1" in out, out
    assert _statuses(path) == ["review", "new"]                     # 反向断言：dry-run 零写入
    assert _statuses(path, "card_reviews") == ["review"]
    assert not list(tmp_path.glob("*.bak.*"))                       # 也不该产生备份


def test_apply_migrates_and_backs_up(tmp_path, monkeypatch, capsys):
    """--apply：先落备份、再迁两张表的旧词表。"""
    path = _legacy_db(tmp_path)
    _patch(monkeypatch, tmp_path, path, ["migrate", "--apply"])
    mig.main()
    out = capsys.readouterr().out
    assert "备份" in out and "cards 1; card_reviews 1" in out, out
    assert _statuses(path) == ["reviewing", "new"]
    assert _statuses(path, "card_reviews") == ["reviewing"]
    baks = list((tmp_path / "data-local").glob("legacy.sqlite3.bak.*"))
    assert len(baks) == 1 and baks[0].stat().st_size > 0, "必须先备份再写库"


def test_apply_is_idempotent(tmp_path, monkeypatch, capsys):
    """连跑两次：第二次 0 行、状态不变、不再产生第二份备份。"""
    path = _legacy_db(tmp_path)
    _patch(monkeypatch, tmp_path, path, ["migrate", "--apply"])
    mig.main()
    capsys.readouterr()
    mig.main()
    out = capsys.readouterr().out
    assert "cards 0; card_reviews 0" in out, out
    assert _statuses(path) == ["reviewing", "new"]
    assert len(list((tmp_path / "data-local").glob("legacy.sqlite3.bak.*"))) == 1
