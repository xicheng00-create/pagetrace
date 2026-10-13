"""出题服务（QUIZ-001/002/003 + QUIZ-012）：**缓存优先 → LLM 批量一次出题 → 机械降级**。

铁律：
- **绝不绕过缓存直连 LLM**（QUIZ-002 无旁路）：会话每张卡先查 `quiz_items`，
  命中直接复用（同输入连跑两次 → 第二次新增 0）；只有缓存未命中才批量出题。
- LLM 调用照抄「AI学习小组app」`backend/ai/agents.py`：`requests` + 超时 + 异常返回 None。
- **题型必须逐字兑现（QUIZ-012）**：每张卡的 `want` 指定题型，提示词按题型分别给规则与**同型 JSON 骨架**；
  LLM 返回另一种题型 → 拒绝（走降级），并记 `logging.warning`（旧版提示词骨架写死 `type=bool`，
  导致「要选择题却永远拿到是非题」→ 全部降级，见 `reports/quiz-fallback-2026-10-03.md`）。
- **失败降级（QUIZ-003）**：LLM 返错/返空/超时 → 机械派生，`source='fallback'`，必记 `logging.warning`；
  题干与选项文本全部回溯库内（卡 front / answer_points、同章其他卡答案要点），**不新增事实**。
  干扰项**不得取纯名词标签**且按 `card_id` 确定性抽签（QUIZ-012：旧版 `pool[:2]` 让同章每题干扰项完全相同）。
- `content_hash = sha256(card_id|type|stem)`，UNIQUE 去重；`card_content_hash` = 出题时卡 front/back 指纹，
  复用前须与卡当前 `content_hash` 一致，不一致 → 同 id 覆盖重生（QUIZ-011）。
"""

from __future__ import annotations

import hashlib
import json
import logging

from config import BaseConfig

from services import cards as card_pool
from services import language
from services.clock import now_iso
from services.quizcontext import card_context  # noqa: F401
from services.quizparse import _parse_json

# 题面文本层（QUIZ-012 拆模块）：本服务只做「缓存 → LLM → 降级」编排，文本规则全在 quiztext
from services.quiztext import (  # noqa: F401  （TYPES/BOOL_OPTIONS/DISTRACTOR_MIN_CHARS 为向后兼容再导出）
    BOOL_OPTIONS,
    DISTRACTOR_MIN_CHARS,
    TYPES,
    bool_options,
    is_gloss_label,
    pick_distractors,
    usable_distractor,
)
from services.quiztext import points as _points
from services.quiztext import system_prompt as _system_prompt
from services.quiztext import validate as _validate

logger = logging.getLogger(__name__)


class QuizGenError(Exception):
    """出题参数错误；由 API 层翻译成 4xx。"""


def content_hash(card_id: int, type_: str, stem: str) -> str:
    return hashlib.sha256(f"{card_id}|{type_}|{stem}".encode()).hexdigest()


def _cfg(key: str, default=None):
    """读配置：有 Flask 上下文走 app.config，单测无上下文时回落环境变量。"""
    from flask import current_app, has_app_context

    if has_app_context():
        return current_app.config.get(key, default)
    import os

    return getattr(os, "environ").get(key, default)


# —— LLM（QUIZ-002：仅生成草稿题；判分绝不走此处） ——
def _chat(messages: list[dict]) -> str | None:
    """请求 DeepSeek chat completions；任何异常/超时/非 2xx 返回 None。"""
    from services.llm import complete

    try:
        return complete(messages, feature="quiz", thinking_disabled=False)
    except Exception:  # noqa: BLE001 —— 既有出题失败降级语义不变
        return None


def assign_types(n: int) -> list[str]:
    """按配置配比（默认 choice:bool = 7:3）分配题型，顺序稳定。"""
    total = BaseConfig.QUIZ_CHOICE_RATIO + BaseConfig.QUIZ_BOOL_RATIO
    n_bool = n * BaseConfig.QUIZ_BOOL_RATIO // total if total > 0 else 0
    return ["choice"] * (n - n_bool) + ["bool"] * n_bool


def _user_id(user_id=None):
    if user_id is None:
        from flask import g
        user_id = getattr(g, "user_id", None)
    if user_id is None:
        raise QuizGenError("authenticated user required")
    return user_id


def chapter_point_pool(con, chapter_id: int, exclude_card_id: int, user_id=None) -> list[str]:
    """同章其他卡的答案要点池（干扰项来源，全部回溯库内文本）。"""
    rows = card_pool.chapter_answer_pool(con, chapter_id, exclude_card_id, _user_id(user_id)).fetchall()
    pool: list[str] = []
    for r in rows:
        for p in _points(r["back"]):
            if p not in pool:
                pool.append(p)
    return pool


def mechanical_item(con, card: dict, type_: str) -> dict:
    """机械派生（QUIZ-003）：不新增事实，文本全部来自卡自身或同章其他卡。"""
    pts = _points(card.get("back"))
    front = (card.get("front") or "").strip()
    if type_ == "choice" and pts and not is_gloss_label(pts[0]):
        correct = pts[0]
        pool = chapter_point_pool(con, card["chapter_id"], card["card_id"], card.get("user_id"))
        distractors = pick_distractors(pool, correct, card["card_id"])
        if distractors:  # 选项数 ≥2 才算合法选择题
            return {
                "type": "choice",
                "stem": front or correct,
                "options": sorted([correct, *distractors]),
                "answer_key": correct,
                "source": "fallback",
                "model": None,
            }
    # 是非题（含「选择题无法凑够干扰项」的退化，仍属 fallback）
    # 语种跟随卡文（QUIZ-011）：英文卡不得出现「判断：」这类汉字前缀。
    if language.is_english_card(card):
        stem = f"True or False: {pts[0]}" if pts else (front or "True or False")
    else:
        stem = f"判断：{pts[0]}" if pts else (front or "判断下列命题")
    options = bool_options(card)
    return {
        "type": "bool",
        "stem": stem,
        "options": options,
        "answer_key": options[0],
        "source": "fallback",
        "model": None,
    }


def llm_batch(cards: list[dict], types: list[str]) -> dict[int, dict]:
    """一次 LLM 调用为多张卡出题；失败/返空 → 空 dict（调用方走降级）。"""
    model = _cfg("DEEPSEEK_MODEL", "deepseek-chat")
    out = _chat([{"role": "system", "content": _system_prompt(cards, types)}])
    parsed = _parse_json(out)
    raw = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        return {}
    by_card = {
        int(x["card_id"]): x for x in raw if isinstance(x, dict) and str(x.get("card_id", "")).isdigit()
    }
    out_map: dict[int, dict] = {}
    for c, t in zip(cards, types, strict=True):
        raw_item = by_card.get(c["card_id"])
        ok = _validate(raw_item, t, bool_options(c) if t == "bool" else None)
        if ok:
            ok["model"] = model
            out_map[c["card_id"]] = ok
        elif isinstance(raw_item, dict) and raw_item.get("type") != t:
            # QUIZ-012 可观测性：题型不符是「提示词骨架骗住模型」这一类缺陷的唯一现场证据
            logger.warning(
                "quiz 题型不符：卡 %s 要 %s，LLM 返 %s → 该卡产出作废（走降级）",
                c["card_id"],
                t,
                raw_item.get("type"),
            )
    return out_map


# —— 缓存读写 ——
def _row_to_item(row) -> dict:
    return {
        "id": row["id"],
        "card_id": row["card_id"],
        "type": row["type"],
        "stem": row["stem"],
        "options": json.loads(row["options"]),
        "answer_key": row["answer_key"],
        "source": row["source"],
    }


def card_content_hash_of(con, card_id: int, user_id=None) -> str | None:
    """该卡当前 front/back 的指纹（与 cards.content_hash 同源，QUIZ-011）。"""
    row = card_pool.card_content_hash(con, card_id, _user_id(user_id)).fetchone()
    return row["content_hash"] if row is not None else None


def cached_item(con, card_id: int, user_id=None):
    """取该卡缓存题：**优先未作答过的**（QUIZ-002），无则复用最少作答的那道。

    QUIZ-011：仅 `card_content_hash` 与该卡当前 `content_hash` 一致才算命中；卡文换过 → 未命中、同 id 重生。
    """
    if user_id is None:
        from flask import g

        user_id = getattr(g, "user_id", None)
        if user_id is None:
            raise QuizGenError("authenticated user required")
    row = card_pool.current_cached_quiz_item(con, card_id, user_id).fetchone()
    return _row_to_item(row) if row is not None else None


def insert_item(con, card_id: int, item: dict, card_content_hash: str | None = None, user_id=None) -> dict:
    """入库（content_hash UNIQUE，INSERT OR IGNORE 幂等），返回完整行。"""
    h = content_hash(card_id, item["type"], item["stem"])
    if card_content_hash is None:
        card_content_hash = card_content_hash_of(con, card_id, user_id)
    con.execute(
        "INSERT OR IGNORE INTO quiz_items(card_id,type,stem,options,answer_key,points,source,"
        "content_hash,card_content_hash,model,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            card_id,
            item["type"],
            item["stem"],
            json.dumps(item["options"], ensure_ascii=False),
            item["answer_key"],
            1,
            item["source"],
            h,
            card_content_hash,
            item.get("model"),
            now_iso(),
        ),
    )
    row = con.execute("SELECT * FROM quiz_items WHERE content_hash=?", (h,)).fetchone()
    return _row_to_item(row)


def update_item(con, item_id: int, card_id: int, item: dict, card_content_hash: str | None = None, user_id=None) -> dict:
    """**同 id 覆盖重生**（QUIZ-011）：卡文变化后旧题失效，保留 `id` 与 quiz_attempts 外键。"""
    h = content_hash(card_id, item["type"], item["stem"])
    if card_content_hash is None:
        card_content_hash = card_content_hash_of(con, card_id, user_id)
    con.execute(
        "UPDATE quiz_items SET type=?, stem=?, options=?, answer_key=?, points=?, source=?,"
        " content_hash=?, card_content_hash=?, model=? WHERE id=?",
        (
            item["type"],
            item["stem"],
            json.dumps(item["options"], ensure_ascii=False),
            item["answer_key"],
            1,
            item["source"],
            h,
            card_content_hash,
            item.get("model"),
            item_id,
        ),
    )
    row = con.execute("SELECT * FROM quiz_items WHERE id=?", (item_id,)).fetchone()
    return _row_to_item(row)


def _produce(con, cards: list[dict], types: list[str]) -> dict[int, dict]:
    """LLM 批量出题 → 失败逐卡机械降级（QUIZ-002/003）；不落库，返回 card_id → item。"""
    produced = llm_batch(cards, types)
    out: dict[int, dict] = {}
    for card, t in zip(cards, types, strict=True):
        item = produced.get(card["card_id"])
        if item is None:
            logger.warning("quiz fallback：卡 %s 期望 %s，LLM 无可用产出 → 机械派生", card["card_id"], t)
            item = mechanical_item(con, card, t)
        out[card["card_id"]] = item
    return out


def ensure_items(con, cards: list[dict], user_id=None) -> list[dict]:
    """为给定卡逐张取/造一道题，返回与输入同序的 item 列表（会话无重复卡由调用方保证）。"""
    chosen: dict[int, dict] = {}
    need: list[dict] = []
    for c in cards:
        hit = cached_item(con, c["card_id"], user_id)
        if hit is not None:
            chosen[c["card_id"]] = hit
        else:
            need.append(c)

    if need:  # 只有未命中缓存的卡才出题 —— 绝不绕过缓存直连 LLM
        types = assign_types(len(need))
        produced = _produce(con, need, types)
        for card in need:
            item = produced[card["card_id"]]
            # 旧行存在但卡文已变（card_content_hash 不符）→ 同 id 覆盖重生，别删别插（QUIZ-011）
            existing = con.execute(
                "SELECT id FROM quiz_items WHERE card_id=? ORDER BY id ASC LIMIT 1", (card["card_id"],)
            ).fetchone()
            if existing is not None:
                chosen[card["card_id"]] = update_item(con, existing["id"], card["card_id"], item, user_id=user_id)
            else:
                chosen[card["card_id"]] = insert_item(con, card["card_id"], item, user_id=user_id)
        con.commit()

    return [chosen[c["card_id"]] for c in cards]


