"""MAST-003 / MAST-007：四态词表**唯一来源 = config** · 前端零映射 · 库约束只许四态。

条款若无机械断言即为未完成（CLAUDE.md §10）：本文件把「词表单一真相 + 前端零映射 + 未知值处置」
变成可跑判据；跨 app 的内部值口径以本 app（`reviewing`）为准。
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import BaseConfig  # noqa: E402
from services import labels  # noqa: E402

VOCAB = {"new": "未学习", "learning": "学习中", "reviewing": "复习中", "mastered": "已掌握"}


def test_vocab_has_exactly_one_home():
    assert BaseConfig.STATUS_LABELS == VOCAB
    assert labels.STATUS_LABELS is BaseConfig.STATUS_LABELS   # 同一对象：不得另存一份
    assert labels.UNKNOWN_LABEL == BaseConfig.STATUS_UNKNOWN_LABEL == "未学习"


@pytest.mark.parametrize("key,label", sorted(VOCAB.items()))
def test_label_lookup(key, label):
    assert labels.status_label(key) == label
    assert labels.status_label(f"  {key}  ") == label          # 容忍库内空白脏值


def test_unknown_status_falls_back_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        assert labels.status_label("review") == "未学习"       # 旧内部值：迁移后不该出现，仍须防
        assert labels.status_label(None) == "未学习"           # NULL
    assert len(caplog.records) == 2, "未知/空状态必须逐条记 warning（不得静默）"
    assert "未知卡片状态" in caplog.text


def test_db_check_admits_exactly_the_four_states():
    src = (BACKEND / "data" / "models.py").read_text(encoding="utf-8")
    assert "CHECK (status IN ('new','learning','reviewing','mastered'))" in src
    assert src.count("CHECK (status IN ('new','learning','reviewing','mastered'))") == 2   # cards + card_reviews


def test_frontend_has_no_status_literals():
    """前端零映射（MAST-003）：标签一律由后端下发，前端不得复制词表或自拼文案。

    - 硬禁：`new` / `learning` / `reviewing` 三个内部值（JS 里根本没有使用场景）。
    - 限用：`mastered` 只许出现在**比较表达式**里（卡面强调色），不得作为文案/映射键。
    - 允许：路由名 `'review'`（`#/review` 视图，与卡状态无关）。
    - 禁止：`new: '未学习'` 这类映射表。
    """
    offenders: list[str] = []
    hard_ban = ("'reviewing'", '"reviewing"', "'learning'", '"learning"', "'new'", '"new"')
    table = re.compile(r"(?:'|\")(?:new|learning|reviewing|mastered)(?:'|\")\s*:")
    cmp_use = re.compile(r"(?:[=!]==?\s*['\"]mastered['\"]|['\"]mastered['\"]\s*[=!]=)")
    for path in sorted((BACKEND / "frontend" / "js").glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for token in hard_ban:
            if token in text:
                offenders.append(f"{path.name}: 内部值字面量 {token}")
        if table.search(text):
            offenders.append(f"{path.name}: 疑似前端状态映射表")
        for i, line in enumerate(text.splitlines(), 1):
            if ("'mastered'" in line or '"mastered"' in line) and not cmp_use.search(line):
                offenders.append(f"{path.name}:{i}: 'mastered' 非比较用法（疑似文案/映射）")
    assert not offenders, "前端出现状态映射（应全部由后端下发 label）：" + "；".join(offenders)
