"""门禁不得把生产库交给任何可写应用实例。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import create_app


def test_production_db_path_rejected(monkeypatch, tmp_path):
    production = Path(__file__).resolve().parents[1] / 'data-local/review.sqlite3'
    monkeypatch.setenv('REVIEW_ISOLATED_RUN', '1')
    monkeypatch.setenv('DATABASE_PATH', str(production))
    with pytest.raises(RuntimeError, match='refuses production database'):
        create_app()
    alias = tmp_path / 'production-link.sqlite3'
    alias.symlink_to(production)
    monkeypatch.setenv('DATABASE_PATH', str(alias))
    with pytest.raises(RuntimeError, match='refuses production database'):
        create_app()


def test_runtime_environment_overrides_imported_config(monkeypatch, tmp_path):
    from config import BaseConfig
    from data.db import _db_path
    monkeypatch.setattr(BaseConfig, 'DATABASE_PATH', '/stale/import/path')
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'safe.sqlite3'))
    app = create_app()
    with app.app_context():
        assert _db_path() == str(tmp_path / 'safe.sqlite3')


def test_hardlink_production_rejected_without_writes(monkeypatch, tmp_path):
    import os
    import sqlite3
    production = Path(__file__).resolve().parents[1] / 'data-local/review.sqlite3'
    alias = tmp_path / 'hardlink.sqlite3'
    os.link(production, alias)
    def snapshot(con):
        return (con.execute('PRAGMA data_version').fetchone()[0],
                tuple(con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                      for t in ('cards', 'card_reviews', 'upload_jobs', 'card_drafts')))
    try:
        with sqlite3.connect(f'file:{production}?mode=ro', uri=True) as original, \
                sqlite3.connect(f'file:{alias}?mode=ro&immutable=1', uri=True) as linked:
            before = snapshot(original), snapshot(linked)
            for path in (str(alias), str(alias) + '/', os.path.relpath(alias),
                         f'file:{alias}?mode=rw', f'sqlite:///{alias}'):
                monkeypatch.setenv('DATABASE_PATH', path)
                monkeypatch.setenv('REVIEW_ISOLATED_RUN', '1')
                with pytest.raises(RuntimeError, match='refuses production database'):
                    create_app()
            after = snapshot(original), snapshot(linked)
            print('hardlink read-only snapshots:', before, after)
            assert before == after
    finally:
        alias.unlink()


def test_uri_fallback_rejected(monkeypatch):
    from config import BaseConfig
    production = Path(__file__).resolve().parents[1] / 'data-local/review.sqlite3'
    monkeypatch.delenv('DATABASE_PATH', raising=False)
    monkeypatch.setattr(BaseConfig, 'DATABASE_PATH', None)
    monkeypatch.setattr(BaseConfig, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{production.parent}/../data-local/review.sqlite3/')
    with pytest.raises(RuntimeError, match='refuses production database'):
        create_app()


def test_production_without_markers_is_allowed(monkeypatch):
    """授权契约：无孤立标记的进程 = 生产运行，**必须能连生产库启动**。

    （2026-10-12 实测事故：门禁无条件拒绝生产库 ⇒ FLASK_ENV=production 启动即抛，
    线上服务一旦重启就全站 500。生产可用性优先于「标记被清也要拒」的旧口径。）
    这里只调判定函数，不建表/不迁移 —— 避免测试真去写生产库。
    """
    import flask
    from data import db as db_mod
    production = Path(__file__).resolve().parents[1] / 'data-local/review.sqlite3'
    monkeypatch.delenv('REVIEW_ISOLATED_RUN', raising=False)
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    monkeypatch.delenv('ALLOW_PRODUCTION_DB', raising=False)
    monkeypatch.setenv('DATABASE_PATH', str(production))
    probe = flask.Flask('probe', root_path=str(Path(__file__).resolve().parents[1] / 'backend'))
    with probe.app_context():
        db_mod.reject_production_path()  # 不抛 = 生产可启动


def test_isolated_run_refuses_production_and_allow_flag_is_exception(monkeypatch):
    """孤立运行（门禁）必须拒生产库；只有显式 ALLOW_PRODUCTION_DB=1 才放行。"""
    import flask
    from data import db as db_mod
    production = Path(__file__).resolve().parents[1] / 'data-local/review.sqlite3'
    probe = flask.Flask('probe', root_path=str(Path(__file__).resolve().parents[1] / 'backend'))
    monkeypatch.setenv('DATABASE_PATH', str(production))
    monkeypatch.setenv('REVIEW_ISOLATED_RUN', '1')
    monkeypatch.delenv('ALLOW_PRODUCTION_DB', raising=False)
    with probe.app_context():
        with pytest.raises(RuntimeError, match='refuses production database'):
            db_mod.reject_production_path()
        monkeypatch.setenv('ALLOW_PRODUCTION_DB', '1')
        db_mod.reject_production_path()  # 显式例外（部署/入库脚本专用）


def test_gate_targets_mark_themselves_isolated_and_never_allow_production():
    """门禁入口必须自带孤立标记，且**不得**继承 ALLOW_PRODUCTION_DB 授权。"""
    makefile = (Path(__file__).resolve().parents[1] / 'Makefile').read_text(encoding='utf-8')
    for target in ('test:', 'smoke:'):
        block = makefile.split(target, 1)[1].split('\n\n', 1)[0]
        assert 'REVIEW_ISOLATED_RUN=1' in block, f'{target} 未标记孤立运行'
        assert 'ALLOW_PRODUCTION_DB' not in block, f'{target} 不得携带生产授权'


def test_attach_production_refused_without_writes(monkeypatch, tmp_path):
    import sqlite3
    from data.db import get_db
    production = Path(__file__).resolve().parents[1] / 'data-local/review.sqlite3'
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'safe.sqlite3'))
    app = create_app()
    with sqlite3.connect(f'file:{production}?mode=ro', uri=True) as observer:
        def snapshot():
            return (observer.execute('PRAGMA data_version').fetchone()[0],
                    observer.execute('SELECT COUNT(*) FROM cards').fetchone()[0])
        before = snapshot()
        with app.app_context():
            con = get_db()
            with pytest.raises(sqlite3.DatabaseError, match='not authorized'):
                con.execute('ATTACH DATABASE ? AS other', (str(production),))
            assert [r[1] for r in con.execute('PRAGMA database_list')] == ['main']
        assert snapshot() == before
