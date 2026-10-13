"""取时入口单点 + 时区偏移口径（DESIGN_SPEC §3.16 TIME-001 · 口径可证伪）。

两条断言（均为**机械**判据，不靠自觉）：
- `test_single_now_source`：AST 扫 `backend/**/*.py`，白名单外出现 `datetime.now(` → fail；
- `test_clock_iso_offset`：`clock.now_iso()` 以 `+08:00` 结尾；UTC 例外（`quiz._utc_iso`）以 `+00:00` 结尾。

白名单每一条都必须写「用途 + 为何不能走 `clock`」——加白名单 = 显式承认第二取时入口。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

# (相对 backend 的路径, 所在函数名) → 理由
ALLOWED: dict[tuple[str, str], str] = {
    ("services/clock.py", "now"): "业务默认取时唯一入口（TZ8 东八区）",
    ("services/quiz.py", "_utc_iso"): "QUIZ-006 明文例外：quiz_attempts.created_at 用 UTC",
    ("scripts/ingest_kb.py", "_now"): "入库时间戳：卡片/复习记录口径一致（+08:00）",
    ("scripts/backfill_subject_labels.py", "backup_db"): "仅供备份文件名，不写任何业务字段",
}


def _now_calls(path: Path) -> list[tuple[str, int]]:
    """返回 [(所在函数名, 行号)]；模块级调用记作 '<module>'。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[tuple[str, int]] = []

    def scan(body, fname: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scan(node.body, node.name)      # 进函数：用函数名归因
                continue
            for sub in ast.walk(node):
                func = getattr(sub, "func", None)
                if isinstance(sub, ast.Call) and isinstance(func, ast.Attribute) and func.attr == "now":
                    hits.append((fname, sub.lineno))

    scan(tree.body, "<module>")
    return hits


def test_single_now_source():
    """TIME-001：`datetime.now(` 只能出现在白名单位置（新增取时入口必须显式登记 + 说明理由）。"""
    offenders: list[str] = []
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        for func, lineno in _now_calls(path):
            if (rel, func) not in ALLOWED:
                offenders.append(f"{rel}:{lineno} → 在 {func}() 内调用 datetime.now()")
    assert not offenders, (
        "取时入口必须单点（DESIGN_SPEC §3.16 TIME-001）：白名单外的 datetime.now() 需先登记理由，"
        "否则跨偏移字符串直比会静默差 8 小时。\n  " + "\n  ".join(offenders)
    )


def test_clock_iso_offset():
    """TIME-001：默认口径 = 东八区（`+08:00`）；UTC 只允许是 `quiz_attempts` 那一个例外。"""
    from services import clock, quiz

    assert clock.now_iso().endswith("+08:00"), clock.now_iso()
    assert clock.iso(clock.now()).endswith("+08:00"), clock.iso(clock.now())
    assert quiz._utc_iso().endswith("+00:00"), quiz._utc_iso()
