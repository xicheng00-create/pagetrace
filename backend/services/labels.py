"""卡片状态标签（MAST-003 / MAST-005）：库内 `cards.status` → 唯一中文标签。

**词表唯一来源 = `config.BaseConfig.STATUS_LABELS`**（本模块只取词，不另立一份）；
**只在后端算**（前端零映射：不得出现 status→中文 的映射表）：

    new→未学习 / learning→学习中 / reviewing→复习中 / mastered→已掌握

未知 `status` → 回落「未学习」并**记 warning**（不得静默）。
"""
from __future__ import annotations

import logging

from config import BaseConfig

logger = logging.getLogger(__name__)

STATUS_LABELS = BaseConfig.STATUS_LABELS
UNKNOWN_LABEL = BaseConfig.STATUS_UNKNOWN_LABEL


def status_label(status: str | None) -> str:
    """把库内 status 映射为四态之一的标签；未知 → 「未学习」+ warning。"""
    key = "" if status is None else str(status).strip()
    if key in STATUS_LABELS:
        return STATUS_LABELS[key]
    logger.warning("未知卡片状态 %r → 回落「%s」（MAST-003）", status, UNKNOWN_LABEL)
    return UNKNOWN_LABEL


SUB_SEP = " · "


def subtitle_of(title: str | None, concept_name: str | None = None) -> str | None:
    """子卡短名（CARD-007 / UI-019）：契约 `title` 是「概念名 · 子卡短名」复合格式。

    - 有 `SUB_SEP` → 取**最后一段**（概念名可能跨语言/带限定语，只认分隔符右侧）。
    - 无 `SUB_SEP` → 整条 `title` 就是子卡标题（老式标题）。
    - 结果为空、或**与概念名相同**（未切分卡 `title = 概念名`）→ `None`：不显示，避免「合成示例书10 · 合成示例书10」。
    - 前端零推导：卡面短名一律读后端本字段，不得前端 split。
    """
    t = str(title or "").strip()
    if not t:
        return None
    sub = t.rsplit(SUB_SEP, 1)[1].strip() if SUB_SEP in t else t
    if not sub or sub == str(concept_name or "").strip():
        return None
    return sub


def display_fields(card, concept_name=None):
    """展示字段唯一入口：前端只转义和渲染，不拆原文或拼出处。"""
    subtitle = subtitle_of(card.get('title'), concept_name or card.get('concept'))
    source = ' · '.join(str(card[k]) for k in ('book', 'chapter', 'concept') if card.get(k))
    if subtitle:
        source += ' · ' + subtitle
    label = status_label(card.get('status'))
    return {'subtitle': subtitle, 'answer_points': [p for p in (card.get('back') or '').splitlines() if p.strip()],
            'source_label': source, 'source_status_label': source + ' · ' + label,
            'source_points_label': source + ' · 要点'}
