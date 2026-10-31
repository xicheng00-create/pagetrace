"""tutor 上下文装配：命中卡 + 概念 + 用户错题摘要 + 计划数据（规格 v0.1 §2/§6）。

**只读**：本模块只有 SELECT，不改任何用户数据（写用户数据必须走 tutor_actions 确认流，第 2 步）。
身份一律显式传 `user_id`；错题/到期队列复用既有 `services.card_quiz_pool` 的按用户口径，
不自建第二套「什么算错题 / 什么算到期」的判定。
"""
from __future__ import annotations

from config import BaseConfig
from flask import current_app, has_app_context
from services import card_quiz_pool
from services.clock import iso as clock_iso
from services.clock import now as clock_now

from ai import rag

WRONG_LIMIT = 5


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


def gather(con, user_id, *, mode: str, message: str, card_id=None,
           subject_id=None, chapter_id=None, concept_id=None) -> dict:
    """装配一次对话要用的全部上下文。mode=card 且卡不可见 → 抛 CardNotFound（调用方转 404）。

    `concept_id` 来自澄清反问的点选：命中就**跳过检索**，直接在该概念下取卡（规格 §9e）；
    概念不可见 → 抛 ConceptNotFound（调用方转 404）。
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
        }
    else:
        picked = rag.pick(con, message, user_id=user_id, subject_id=subject_id,
                          chapter_id=chapter_id, top_k=top_k)
        ctx = {
            "mode": mode,
            "hits": picked["cards"],
            "concepts": rag.retrieve_concepts(con, message, user_id=user_id, subject_id=subject_id,
                                              chapter_id=chapter_id, top_k=3),
            "card": None,
            "wrong": [],
            "plan": None,
            "picked_concept": None,
            "retrieval": {"weak": picked["weak"], "top_coverage": picked["top_coverage"],
                          "alias_hits": len(picked["alias_hits"]), "options": picked["options"],
                          "via": "alias" if picked["alias_hits"] else "exact", "empty": not picked["cards"]},
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
