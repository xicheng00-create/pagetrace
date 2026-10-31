"""概念表路由（规格 `~/AgentMemory/projects/xueer-tutor-spec.md` §9f）。

**为什么存在**：纯 2-gram 对口语问句几乎够不着（实测 gold@5 = 0.12），而「让模型直接从概念名清单里挑 3 个」
实测 3.4/5 —— 差了一个数量级。本模块只做这一件事：把该用户**可见范围**内的概念名（一行一个）喂给模型，
要它原样抄回最相关的 3 个。

**硬边界（改这里之前先读）**：
- 只读：本模块只有 SELECT（经 `ai/rag.visible_concepts`），不写任何表、不动 `cards`；
- 不猜：只认**完全等于已知概念名**的行（去空白、去编号/括号/引号）；对不上就是 `[]`，
  绝不拿「差不多像」的名字去改库里的名字；
- 不抛：异常 / 超时（默认 8 秒，`TUTOR_ROUTE_TIMEOUT`）/ 乱码 / 空回复 → 一律 `[]` 并记日志，
  上层据此静默退回 2-gram（规格 §9f 第四条）；
- 不新增依赖、不引向量库：一次普通 chat completion 而已。

**返回形状**：`pick()` 按规格返回 `list[str]`（0–3 个概念名）；`pick_detailed()` 额外带 token 与耗时，
供 `ai/tutor.py` 把这次调用**累加进账**（路由不额外扣用户次数，但花掉的 token 必须记）。
"""
from __future__ import annotations

import logging
import re
import time

from config import BaseConfig
from flask import current_app, has_app_context
from services import card_quiz_pool, llm

from ai import rag

# 路由口径常量（规格 §9f）：一次最多要 3 个；超时 8 秒；输入清单按可见范围全量给。
ROUTE_LIMIT = 3
DEFAULT_TIMEOUT = 8
FEATURE = "tutor_route"  # 单独一个 feature：用量账里能把这部分成本与作答区分开

ROUTE_SYSTEM = """你是「学而时习之」复习 app 的检索路由，只做一件事：从下面的概念名清单里，
挑出与学习者这句话最相关的概念名。

硬规则：
1. 只能从清单里**原样抄写**，一个字都不许改；不许自创、不许翻译、不许缩写、不许解释。
2. 每行一个概念名，不要编号、不要引号、不要标点、不要空格。
3. 最多 {limit} 个；确实一个都不相关就只输出「无」。
4. 不要回答问题本身，不要输出清单以外的任何内容。
"""

ROUTE_TEMPLATE = """学习者这句话：{message}

概念名清单（共 {count} 个，一行一个）：
{names}
"""

_LOG = logging.getLogger(__name__)

# 行首编号 / 项目符号（「1. 」「2、」「(3) 」「- 」「• 」）——只去这些，不改名字本身
_NUMBERING = re.compile(r"^(?:[-*•·]+|\d+\s*[.、)）．:：]|[(（]\d+[)）])\s*")
# 行尾标点（模型爱加的句号/顿号/分号），去之前先原样比对一次
_TRAILING = "，。、；;：:,．."
# 模型偶尔套的括号/引号（【】「」（）() "" '' ``），同样只在原样对不上时才去
_WRAPPERS = (("【", "】"), ("「", "」"), ("『", "』"), ("（", "）"), ("(", ")"),
             ("《", "》"), ('"', '"'), ("'", "'"), ("`", "`"))


def _cfg(key, default):
    if has_app_context():
        return current_app.config.get(key, default)
    return getattr(BaseConfig, key, default)


def _timeout() -> int:
    try:
        value = int(_cfg("TUTOR_ROUTE_TIMEOUT", DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _scope_kwargs(scope) -> dict:
    """scope = 请求带来的收窄条件（`{"subject_id":…, "chapter_id":…}` 或 None = 全可见范围）。"""
    if not scope:
        return {}
    if not isinstance(scope, dict):
        raise TypeError("scope 必须是 dict 或 None")
    return {"subject_id": scope.get("subject_id"), "chapter_id": scope.get("chapter_id")}


def _candidates(line: str) -> list[str]:
    """一行的三种可能读法：原样 / 去编号 / 再去括号引号。按顺序试，命中即用。"""
    raw = (line or "").strip()
    if not raw:
        return []
    out = [raw]
    stripped = _NUMBERING.sub("", raw).strip()
    if stripped != raw:
        out.append(stripped)
    for item in list(out):
        inner = item.rstrip(_TRAILING).strip()
        if inner and inner != item:
            out.append(inner)
        for left, right in _WRAPPERS:
            if len(item) > len(left) + len(right) and item.startswith(left) and item.endswith(right):
                out.append(item[len(left):-len(right)].strip())
    return out


def parse(reply, known) -> list[str]:
    """只认完全等于已知概念名的行（去空白、去编号、去括号引号）；不足 3 个有几个算几个。"""
    if not reply:
        return []
    picked: list[str] = []
    for line in str(reply).splitlines():
        for candidate in _candidates(line):
            if candidate in known:
                if candidate not in picked:
                    picked.append(candidate)
                break
        if len(picked) >= ROUTE_LIMIT:
            break
    return picked[:ROUTE_LIMIT]


def _prompt(message: str, names: list[str]) -> list[dict]:
    return [
        {"role": "system", "content": ROUTE_SYSTEM.format(limit=ROUTE_LIMIT)},
        {"role": "user", "content": ROUTE_TEMPLATE.format(
            message=message, count=len(names), names="\n".join(names))},
    ]


def concepts_by_names(con, names, *, user_id, subject_id=None, chapter_id=None) -> list[dict]:
    """概念名 → 概念行（按传入名字的顺序返回；重名取首个；不可见的名字直接丢掉，不猜）。"""
    wanted = [name for name in dict.fromkeys(names or []) if name]
    if not wanted:
        return []
    first: dict[str, dict] = {}
    for row in rag.visible_concepts(con, user_id, subject_id=subject_id, chapter_id=chapter_id):
        first.setdefault(row["concept_name"], row)
    return [first[name] for name in wanted if name in first]


def cards_of_concepts(con, concept_ids, *, user_id, top_k: int = 5) -> list[dict]:
    """概念路由命中后：在这些概念下取卡（规格 §9f「命中概念下取卡」）。

    取法 = 按传入概念顺序**轮流**各取一张（3 个概念 × 5 个位置 → 2/2/1），与脑侧实测脚本
    `concept_router_eval.py` 的配卡方式一致，A11 的分数才与实测 3.4/5 可比。
    卡片读取仍只走卡池单点 `services.card_quiz_pool.retrieval_cards`（UP-006），不写第二套范围 SQL。
    """
    ids = [cid for cid in dict.fromkeys(concept_ids or []) if cid is not None]
    if not ids or top_k <= 0:
        return []
    buckets: dict[int, list[dict]] = {cid: [] for cid in ids}
    for row in card_quiz_pool.retrieval_cards(con, user_id).fetchall():
        if row["concept_id"] not in buckets:
            continue
        buckets[row["concept_id"]].append({
            "card_id": row["card_id"], "concept_id": row["concept_id"],
            "concept_name": row["concept_name"], "chapter_id": row["chapter_id"],
            "chapter_name": row["chapter_name"], "front": row["front"], "back": row["back"],
            "title": row["title"], "score": 1.0, "via": "router",
        })
    for bucket in buckets.values():
        bucket.sort(key=lambda card: card["card_id"])
    out: list[dict] = []
    depth = 0
    while len(out) < top_k and any(depth < len(bucket) for bucket in buckets.values()):
        for cid in ids:
            if len(out) >= top_k:
                break
            if depth < len(buckets[cid]):
                out.append(buckets[cid][depth])
        depth += 1
    return out[:top_k]


def pick_detailed(con, user_id, message, scope=None) -> dict:
    """路由一次，返回 `{names, tokens_in, tokens_out, ms, empty_reason}`；任何失败都不抛。"""
    started = time.monotonic()
    result = {"names": [], "tokens_in": None, "tokens_out": None, "ms": 0, "empty_reason": None}

    def done(reason=None) -> dict:
        result["empty_reason"] = reason
        result["ms"] = int((time.monotonic() - started) * 1000)
        return result

    text = (message or "").strip()
    if not text:
        return done("empty_message")
    try:
        kwargs = _scope_kwargs(scope)
    except TypeError:
        _LOG.warning("概念路由：scope 形状不对，按全范围处理")
        kwargs = {}
    try:
        rows = rag.visible_concepts(con, user_id, **kwargs)
    except Exception:  # 读库失败也不许冒到上层（上层只会 500）
        _LOG.warning("概念路由：读可见概念失败，退回 2-gram", exc_info=True)
        return done("scope_error")
    names = [row["concept_name"] for row in rows]
    if not names:
        return done("no_concepts")

    try:
        reply, usage = llm.complete(_prompt(text, names), feature=FEATURE,
                                    timeout=_timeout(), with_usage=True)
    except Exception as exc:  # 超时 / 5xx / 缺 key / 用量落账失败：一律静默退回
        _LOG.warning("概念路由：模型调用失败（%s），退回 2-gram", type(exc).__name__)
        return done("llm_error")

    usage = usage or {}
    result["tokens_in"] = _count(usage.get("prompt_tokens"))
    result["tokens_out"] = _count(usage.get("completion_tokens"))
    picked = parse(reply, set(names))
    if not picked:
        return done("no_match")
    result["names"] = picked
    return done(None)


def pick(con, user_id, message, scope=None) -> list[str]:
    """规格 §9f 的对外形状：`pick(con, user_id, message, scope) -> list[str]`（0–3 个概念名）。"""
    return pick_detailed(con, user_id, message, scope)["names"]
