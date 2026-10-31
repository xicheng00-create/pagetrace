"""tutor 上下文装配：命中卡 + 概念 + 用户错题摘要 + 计划数据（规格 v0.1 §2/§6）。

**只读**：本模块只有 SELECT，不改任何用户数据（写用户数据必须走 tutor_actions 确认流，第 2 步）。
身份一律显式传 `user_id`；错题/到期队列复用既有 `services.card_quiz_pool` 的按用户口径，
不自建第二套「什么算错题 / 什么算到期」的判定。
"""
from __future__ import annotations

import logging

from config import BaseConfig
from flask import current_app, has_app_context
from services import card_quiz_pool
from services.clock import iso as clock_iso
from services.clock import now as clock_now

from ai import concept_router, rag

WRONG_LIMIT = 5

logger = logging.getLogger(__name__)


def _cfg(key, default):
    if has_app_context():
        return current_app.config.get(key, default)
    return getattr(BaseConfig, key, default)


def card_detail(con, card_id, user_id) -> dict:
    return rag.card_by_id(con, card_id, user_id=user_id)


def wrong_summary(con, user_id, limit: int = WRONG_LIMIT) -> list[dict]:
    """最近错题摘要（按用户）。复用 card_quiz_pool 的错题口径，取前 limit 条。"""
    rows = card_quiz_pool.wrong_answer_cards(con, user_id).fetchall()
    return [
        {"card_id": row["card_id"], "front": row["front"], "wrong_count": row["wrong_count"],
         "stem": row["stem"], "my_answer": row["my_answer"], "correct_answer": row["correct_answer"]}
        for row in rows[:limit]
    ]


def _book_ids(con):
    """用户自选的复习范围（prefs.book_scope）；无 g 上下文（如离线脚本）视为全范围。"""
    from services import scope

    try:
        return scope.get_book_scope(con)
    except RuntimeError:
        return None


def plan_summary(con, user_id) -> dict:
    """今天学什么：到期数 / 新卡数 / 今日目标。数字全部来自既有队列口径。"""
    current = clock_now()
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    book_ids = _book_ids(con)
    due = card_quiz_pool.available_due_count(
        con, clock_iso(current), book_ids, clock_iso(day_start), user_id).fetchone()[0]
    new = card_quiz_pool.available_new_count(con, book_ids, user_id).fetchone()[0]
    return {
        "due": due,
        "new": new,
        "review_target": _cfg("REVIEW_TASK_TARGET", BaseConfig.REVIEW_TASK_TARGET),
        "quiz_target": _cfg("QUIZ_TASK_TARGET", BaseConfig.QUIZ_TASK_TARGET),
        "wrong_total": len(wrong_summary(con, user_id, limit=1000)),
    }


def _route(con, user_id, message, subject_id, chapter_id, top_k) -> tuple[dict, list, list]:
    """概念表路由第一层（规格 §9f）：路由 → 命中概念下取卡。返回 (route, concepts, cards)。

    路由模块自己已经吞掉模型侧的失败；这里再兜一层「路由模块本身抛了」——
    第一层永远不许把 500 带给用户（A11 第二条：路由打桩抛异常 → 退回 2-gram、不 500）。
    """
    try:
        route = concept_router.pick_detailed(
            con, user_id, message,
            {"subject_id": subject_id, "chapter_id": chapter_id})
        if not route["names"]:
            return route, [], []
        concepts = concept_router.concepts_by_names(con, route["names"], user_id=user_id,
                                                   subject_id=subject_id, chapter_id=chapter_id)
        cards = concept_router.cards_of_concepts(con, [row["concept_id"] for row in concepts],
                                                 user_id=user_id, top_k=top_k)
        return route, concepts, cards
    except Exception:
        logger.warning("概念路由异常，退回 2-gram", exc_info=True)
        return ({"names": [], "tokens_in": None, "tokens_out": None, "ms": 0,
                 "empty_reason": "router_exception"}, [], [])



def _routes_this_turn(mode) -> bool:
    """只有自由提问走路由：card 自带卡、quiz/plan 是操作指令（规格 §9f 只给 free 定顺序）。"""
    return mode == "free"


def _merge_options(routed_concepts, options, limit: int) -> list[dict]:
    """澄清候选：路由候选优先，不足 3 个再按 2-gram 重叠补（规格 §9f）。"""
    merged: dict[int, dict] = {}
    for row in routed_concepts or []:
        merged.setdefault(row["concept_id"], {"concept_id": row["concept_id"],
                                              "name": row["concept_name"]})
    for option in options or []:
        if option.get("concept_id") is not None:
            merged.setdefault(option["concept_id"], option)
    return list(merged.values())[:limit]


def gather(con, user_id, *, mode: str, message: str, card_id=None,
           subject_id=None, chapter_id=None, concept_id=None) -> dict:
    """装配一次对话要用的全部上下文。mode=card 且卡不可见 → 抛 CardNotFound（调用方转 404）。

    `concept_id` 来自澄清反问的点选：命中就**跳过检索**，直接在该概念下取卡（规格 §9e）；
    概念不可见 → 抛 ConceptNotFound（调用方转 404）。

    `mode=free` 且没点选时走三层（规格 §9f）：
    **概念表路由 → 命中概念下取卡** → 路由空/概念下无卡才 2-gram + 别名表 → 仍无则澄清反问。
    """
    top_k = int(_cfg("TUTOR_TOP_K", 5))
    if concept_id is not None:
        concept = rag.concept_by_id(con, concept_id, user_id=user_id)
        hits = rag.cards_of_concept(con, concept_id, user_id=user_id, top_k=top_k)
        ctx = {
            "mode": mode,
            "hits": hits,
            "concepts": [{"name": concept["concept_name"], "chapter_name": concept["chapter_name"],
                          "concept_id": concept["concept_id"]}],
            "card": None,
            "wrong": [],
            "plan": None,
            "picked_concept": {"concept_id": concept["concept_id"], "name": concept["concept_name"]},
            "retrieval": {"weak": False, "top_coverage": 1.0, "alias_hits": 0, "options": [],
                          "via": "concept", "empty": not hits},
            "router": None,
        }
    else:
        route, routed_concepts, routed_cards = ({"names": [], "tokens_in": None, "tokens_out": None,
                                                 "ms": 0, "empty_reason": None}, [], [])
        if _routes_this_turn(mode):
            route, routed_concepts, routed_cards = _route(
                con, user_id, message, subject_id, chapter_id, top_k)
        if routed_cards:
            ctx = {
                "mode": mode,
                "hits": routed_cards,
                "concepts": [{"name": row["concept_name"], "chapter_name": row["chapter_name"],
                              "concept_id": row["concept_id"]} for row in routed_concepts],
                "card": None,
                "wrong": [],
                "plan": None,
                "picked_concept": None,
                "retrieval": {"weak": False, "top_coverage": 1.0, "alias_hits": 0, "options": [],
                              "via": "router", "empty": False},
                "router": route,
            }
        else:
            picked = rag.pick(con, message, user_id=user_id, subject_id=subject_id,
                              chapter_id=chapter_id, top_k=top_k)
            ctx = {
                "mode": mode,
                "hits": picked["cards"],
                "concepts": rag.retrieve_concepts(con, message, user_id=user_id,
                                                  subject_id=subject_id,
                                                  chapter_id=chapter_id, top_k=3),
                "card": None,
                "wrong": [],
                "plan": None,
                "picked_concept": None,
                "retrieval": {"weak": picked["weak"], "top_coverage": picked["top_coverage"],
                              "alias_hits": len(picked["alias_hits"]),
                              "options": _merge_options(routed_concepts, picked["options"],
                                                        rag.CLARIFY_MAX_OPTIONS),
                              "via": "alias" if picked["alias_hits"] else "exact",
                              "empty": not picked["cards"]},
                "router": route,
            }

    if mode == "card":
        ctx["card"] = card_detail(con, card_id, user_id)
        # 贴卡讲解：当前卡及其同概念卡优先于全库命中（当前卡是「他正在看的那张」）
        ctx["siblings"] = [
            hit for hit in ctx["hits"] if hit["concept_id"] == ctx["card"]["concept_id"]
        ]
    if mode == "quiz":
        ctx["wrong"] = wrong_summary(con, user_id)
    if mode == "plan":
        ctx["plan"] = plan_summary(con, user_id)
        ctx["wrong"] = wrong_summary(con, user_id, limit=3)
    return ctx
