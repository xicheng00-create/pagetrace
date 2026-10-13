"""统一时钟（DESIGN_SPEC §3.16 TIME-001：ISO 8601 **带显式时区偏移**；「今天」判定交前端本地时区）。

业务默认取时入口：HTTP / ingest / 展示路径的时间戳一律走这里（东八区 `TZ8`）。
**例外**：`quiz_attempts.created_at` 用 UTC（见 `services/quiz.py::_utc_iso`，QUIZ-006 明文规定）。
跨口径比较**必须** Python 侧 `astimezone` 后比，**禁止**跨偏移字符串直比（字典序会差 8 小时）。
取时入口单点由 `tests/test_clock_source.py` 机械断言（白名单外的 `datetime.now(` 即失败）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

TZ8 = timezone(timedelta(hours=8))


def now() -> datetime:
    return datetime.now(TZ8)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def iso(dt: datetime) -> str:
    return dt.astimezone(TZ8).isoformat(timespec="seconds")
