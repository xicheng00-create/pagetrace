"""SQLite 连接与初始化（WAL + busy_timeout）。

单进程 waitress 多线程：每个请求从 Flask g 拿独立连接，
避免跨线程共享 sqlite3.Connection。
"""
import os
import sqlite3
from urllib.parse import unquote, urlsplit

from flask import current_app, g

from data import models


def _db_path() -> str:
    """优先读环境变量 DATABASE_PATH（测试用临时库），否则用 config 的 URI。"""
    path = os.environ.get("DATABASE_PATH") or current_app.config.get("DATABASE_PATH")
    if path:
        return _normalize_path(path)
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    # 仅支持 sqlite:/// 写法；相对路径转成基于 backend 根
    if uri.startswith("sqlite:///"):
        path = uri[len("sqlite:///"):]
        if not os.path.isabs(path):
            path = os.path.join(current_app.root_path, "..", path)
        return _normalize_path(path)
    # 兜底：instance 目录
    return _normalize_path(os.path.join(current_app.root_path, "..", "data-local", "review.sqlite3"))


def _normalize_path(path):
    if path.startswith("sqlite:///"):
        path = path[len("sqlite:///"):]
    if path.startswith("file:"):
        parsed = urlsplit(path)
        if parsed.netloc not in ("", "localhost"):
            raise RuntimeError("unsupported database URI host")
        path = unquote(parsed.path)
    return os.path.abspath(os.path.normpath(path))


def isolated_run() -> bool:
    """孤立运行（门禁/测试）。

    只有这些场景才启用「拒绝生产库」与 ATTACH 禁令；**生产运行必须能连生产库启动**，
    否则一次重启即全站 500（2026-10-12 实测：无条件调用会让 FLASK_ENV=production 启动即抛）。
    """
    return (os.environ.get("REVIEW_ISOLATED_RUN") == "1"
            or bool(os.environ.get("PYTEST_CURRENT_TEST"))
            or bool(getattr(current_app, "testing", False)))


def reject_production_path():
    """门禁必须在任何建表、迁移或 worker 启动之前拒绝真实生产库。

    仅在孤立运行下生效（见 isolated_run）；生产运行直接返回。
    `ALLOW_PRODUCTION_DB=1` 只是孤立运行下的显式例外（部署/入库脚本用），
    不得出现在门禁环境（tests 断言）。
    """
    if not isolated_run():
        return
    production = os.path.join(current_app.root_path, "..", "data-local", "review.sqlite3")
    path = _db_path()
    same = os.path.realpath(path) == os.path.realpath(production)
    if os.path.exists(path) and os.path.exists(production):
        same = same or os.path.samefile(path, production)
    if same and os.environ.get("ALLOW_PRODUCTION_DB") != "1":
        raise RuntimeError("isolated run refuses production database")


def _isolated_connection(con):
    # 在 ATTACH 执行前拒绝，避免连接到第二个库后才发现。
    def authorize(action, _arg1, _arg2, _database, _trigger):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_ATTACH else sqlite3.SQLITE_OK
    con.set_authorizer(authorize)
    if [r[1] for r in con.execute("PRAGMA database_list")] != ["main"]:
        raise RuntimeError("isolated run requires only main database")


def get_db() -> sqlite3.Connection:
    """每个请求一个连接，开启 WAL 与 busy_timeout。"""
    if "db" not in g:
        reject_production_path()
        path = _db_path()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # isolation_level="IMMEDIATE"：事务一开始就取写锁，避免「读事务升级为写」
        # 触发 SQLITE_BUSY_SNAPSHOT（busy_timeout 对此无效，会立即 database is locked）。
        con = sqlite3.connect(path, timeout=15, isolation_level="IMMEDIATE")
        con.row_factory = sqlite3.Row
        if isolated_run():
            _isolated_connection(con)
        # REQ-STATE-01：每连接一张 _mine（当前用户的卡片状态），未刷新时视为全部未学。
        # 必须在隔离检查之后创建：TEMP 表会让 PRAGMA database_list 多出 temp 库。
        con.execute("CREATE TEMP TABLE IF NOT EXISTS _mine(card_id INTEGER PRIMARY KEY,"
                    " status TEXT, learn_count INTEGER, next_review_at TEXT)")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=15000")
        con.execute("PRAGMA foreign_keys=ON")
        g.db = con
    return g.db


def close_db(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_db(app=None):
    """建表 + 迁移；幂等，启动与测试均可调用。"""
    con = get_db()
    fresh = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone() is None
    if fresh:
        from data.s2_schema import FRESH_SCHEMA
        con.executescript(FRESH_SCHEMA)
    else:
        con.executescript(models.SCHEMA)
    models.migrate(con)
    if fresh:
        models.migrate_upload(con)
    con.commit()


def init_app(app):
    """注册 teardown 与 CLI 建表命令。"""
    app.teardown_appcontext(close_db)

    @app.cli.command("init-db")
    def _init_db_cmd():
        with app.app_context():
            init_db(app)
        print("init_db done")
