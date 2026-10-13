"""pagetrace — 应用工厂入口。

职责：加载 .env → 建 Flask app（开发/生产同款进程模型）→ 注册蓝图 → 初始化库 →
静态托管 backend/frontend（PWA）。生产用 waitress（单进程 4 线程）。
"""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
# 让 backend 内部用绝对导入（from data.db import ... / from api.health import ...）
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(REPO_ROOT / ".env")

from api.auth import bp as auth_bp  # noqa: E402
from api.books import bp as books_bp  # noqa: E402
from api.cards import bp as cards_bp  # noqa: E402
from api.chapters import bp as chapters_bp  # noqa: E402
from api.concepts import bp as concepts_bp  # noqa: E402
from api.health import bp as health_bp  # noqa: E402
from api.invites import bp as invites_bp  # noqa: E402
from api.plan import bp as plan_bp  # noqa: E402
from api.progress import bp as progress_bp  # noqa: E402
from api.quiz import bp as quiz_bp  # noqa: E402
from api.quote import bp as quote_bp  # noqa: E402
from api.report import bp as report_bp  # noqa: E402
from api.review import bp as review_bp  # noqa: E402
from api.scope import bp as scope_bp  # noqa: E402
from api.streak import bp as streak_bp  # noqa: E402
from api.subjects import bp as subjects_bp  # noqa: E402
from api.task import bp as task_bp  # noqa: E402
from api.upload import bp as upload_bp  # noqa: E402
from api.weak import bp as weak_bp  # noqa: E402
from config import get_config  # noqa: E402
from data import db as db_mod  # noqa: E402

version = "0.16.2"
FRONTEND_DIR = BACKEND_DIR / "frontend"


def create_app(env: str | None = None) -> Flask:
    app = Flask(
        __name__,
        static_folder=str(FRONTEND_DIR),
        static_url_path="",
    )
    app.config.from_object(get_config(env))
    for key in ("DATABASE_PATH", "UPLOAD_ROOT", "LLM_TIMEOUT"):
        if key in os.environ:
            app.config[key] = os.environ[key]
    if "UPLOAD_WORKER_ENABLED" in os.environ:
        app.config["UPLOAD_WORKER_ENABLED"] = os.environ["UPLOAD_WORKER_ENABLED"] == "1"
    with app.app_context():
        db_mod.reject_production_path()
    app.config["VERSION"] = version  # 唯一版本来源（版本号诚实规则见 CLAUDE.md §5）

    # UP-012 接线自检：provider=proxy 但无密钥 → 上游 401，而失败被收敛成 job failed（现场难查）。
    if app.config.get("LLM_PROVIDER") == "proxy" and not str(app.config.get("LLM_API_KEY") or "").strip():
        logging.getLogger(__name__).warning(
            "LLM_PROVIDER=proxy 但 LLM_API_KEY 为空：出卡/出题调用会 401 失败。"
            "检查 .env 是否缺 LLM_* 接线（DESIGN_SPEC §11 UP-012）。"
        )

    db_mod.init_app(app)
    for _bp in (health_bp, auth_bp, invites_bp, subjects_bp, books_bp, chapters_bp, concepts_bp,
                cards_bp, review_bp, progress_bp, quiz_bp, streak_bp,
                quote_bp, task_bp, plan_bp, weak_bp, report_bp, scope_bp, upload_bp):
        app.register_blueprint(_bp)


    from auth import require_user, unauthorized
    @app.before_request
    def _authentication_gate():
        if request.path.startswith('/api/') and not request.path.startswith('/api/auth/'):
            if require_user() is None:
                return unauthorized()

    @app.errorhandler(404)
    def _not_found(_e):
        return jsonify({"code": 404, "msg": "资源不存在"}), 404

    @app.errorhandler(500)
    def _internal(_e):
        return jsonify({"code": 500, "msg": "服务内部错误"}), 500

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/sw.js")
    def service_worker():
        """Service Worker 必须不被缓存，否则前端升级卡旧版本。"""
        resp = send_from_directory(FRONTEND_DIR, "sw.js")
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    with app.app_context():
        db_mod.init_db()

    from services.worker import start
    start(app)
    return app


if __name__ == "__main__":
    from waitress import serve

    _host = os.environ.get("HOST", "127.0.0.1")
    _port = int(os.environ.get("PORT", "5004"))
    print(f"[boot] pagetrace v{version} (waitress) on {_host}:{_port}", flush=True)
    serve(create_app(), host=_host, port=_port, threads=4)
