"""边界：tutor 不写用户数据、四表带租户列、提示词守住「库内优先」契约。"""
import re
from pathlib import Path

import pytest
from tutor_fixtures import make_app

from ai import concept_router, tutor_context
from ai import tutor_prompts

BACKEND = Path(__file__).resolve().parents[1] / "backend"
WRITE_TABLES = {"conversations", "messages", "tutor_actions", "quota_usage"}
USER_TABLES = {"cards", "card_reviews", "quiz_attempts", "prefs", "books", "concepts",
               "chapters", "subjects", "users", "card_video_links", "video_views"}

# 路由层单独测（tests/test_tutor_router.py）。本文件把路由打空 → 行为等价 0.20.0，且不依赖网络。
_ROUTE_EMPTY = {"names": [], "tokens_in": None, "tokens_out": None, "ms": 0, "empty_reason": "stub"}


@pytest.fixture(autouse=True)
def _no_concept_router(monkeypatch):
    monkeypatch.setattr(concept_router, "pick_detailed", lambda *args, **kwargs: dict(_ROUTE_EMPTY))



@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "boundary.sqlite3"))
    return make_app(tmp_path / "boundary.sqlite3")


def test_tutor_modules_only_write_their_own_tables():
    """静态断言：tutor 侧代码里出现的写语句只能落在四张自己的表上。"""
    targets = ["ai/tutor.py", "ai/tutor_context.py", "ai/tutor_prompts.py", "ai/rag.py",
               "ai/concept_router.py", "services/tutor_quota.py", "api/tutor.py"]
    found = []
    for rel in targets:
        source = (BACKEND / rel).read_text(encoding="utf-8")
        for match in re.finditer(r"\b(INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+(\w+)",
                                 source, re.I):
            table = match.group(2)
            if table.upper() == "SET":  # 「ON CONFLICT ... DO UPDATE SET」不是第二个目标表
                continue
            found.append((rel, match.group(1).upper(), table))
    assert found, "扫描本身要能扫到写语句（否则断言是空的）"
    offenders = [item for item in found if item[2] not in WRITE_TABLES]
    assert not offenders, f"tutor 写了用户数据：{offenders}"
    assert not [item for item in found if item[2] in USER_TABLES]


def test_chat_leaves_user_data_untouched(app):
    """运行时证据：跑一次问答，用户侧各表行数与内容不变。"""
    from data.db import get_db

    watched = ["cards", "card_reviews", "quiz_attempts", "prefs", "books", "concepts"]

    def snapshot():
        with app.app_context():
            con = get_db()
            return {table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in watched}, con.execute(
                        "SELECT group_concat(x, '|') FROM (SELECT front || back AS x FROM cards"
                        " ORDER BY id)").fetchone()[0]

    before = snapshot()
    with app.test_client() as client:
        client.post("/api/tutor/chat", json={"message": "亲密伴侣暴力是什么", "mode": "free"})
        client.post("/api/tutor/chat", json={"message": "今天学什么", "mode": "plan"})
    assert snapshot() == before


def test_tutor_tables_carry_tenant_columns(app):
    from data.db import get_db

    with app.app_context():
        con = get_db()
        for table in ("conversations", "tutor_actions", "quota_usage"):
            columns = {row[1]: row for row in con.execute(f"PRAGMA table_info({table})")}
            assert columns["user_id"][3] == 1, f"{table}.user_id 必须 NOT NULL"
            indexes = [list(con.execute(f'PRAGMA index_info("{row[1]}")'))
                       for row in con.execute(f"PRAGMA index_list({table})")]
            assert any(index and index[0][2] == "user_id" for index in indexes), \
                f"{table} 缺前导 user_id 索引"
            keys = [row for row in con.execute(f"PRAGMA foreign_key_list({table})")]
            assert any(row[2] == "users" and row[3] == "user_id" for row in keys), \
                f"{table} 缺 users 外键"
        messages = {row[1] for row in con.execute("PRAGMA table_info(messages)")}
        assert {"conversation_id", "role", "content", "created_at"} <= messages
        assert "user_id" not in messages  # 归属只经会话，避免两处身份


def test_system_prompt_keeps_library_boundary(app):
    with app.app_context():
        from data.db import get_db

        con = get_db()
        ctx = tutor_context.gather(con, 1, mode="free", message="亲密伴侣暴力包括哪些行为？")
    system = tutor_prompts.build_system(ctx)
    assert tutor_prompts.LIB_OPEN in system and tutor_prompts.LIB_CLOSE in system
    assert "亲密伴侣暴力" in system  # 命中内容进提示词
    assert "不许编造" in system or "编造" in system
    assert "（来源：" in system  # 要求写出来源格式
