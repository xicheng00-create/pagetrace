"""UNI-MASTER 唯一计算点：卡级加权作答与层级汇总。"""
from __future__ import annotations

import math
from datetime import UTC, datetime

from services.clock import now

STATE_SCORES = {"new": 0, "learning": 40, "reviewing": 70, "mastered": 100}
LEVEL_LABELS = {"master": "已掌握", "progress": "进行中", "weak": "薄弱", "na": "未评估"}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)



def card_mastery(status: str, events: list[dict], *, at: str | None = None) -> dict:
    """计算卡级 m、正确率与最小证据；事件时间统一按 UTC 衰减。"""
    at_dt = _utc(at) if at else now().astimezone(UTC)
    earned = 0.0
    maximum = 0.0
    for event in events:
        created = event.get("created_at") or event.get("learned_at")
        if not created:
            continue
        days = max((at_dt - _utc(created)).total_seconds() / 86400, 0)
        weight = 0.5 ** (days / 7)
        points = float(event.get("points") or 1)
        value = event.get("earned")
        earned += weight * (float(value) * points if value is not None else 0)
        maximum += weight * points
    acc = round(100 * earned / maximum) if maximum else None
    state_score = STATE_SCORES.get(status, 0)
    score = round(0.5 * state_score + 0.5 * acc) if acc is not None else state_score
    # 证据 = 有作答证据（≥1 次），与 AI学习小组 app 的 `evidence = count > 0` 一致；
    # 「卡级可判已掌握」的 ≥2 次门槛另属调度口径，不得在此复用（跨 app 一致性红线）。
    return {"m": score, "acc": acc, "evidence": len(events) > 0}


def level_mastery(cards: list[dict]) -> dict:
    """用同一卡级 m 汇总层级，并下发四态。"""
    total = len(cards)
    learned = [card for card in cards if card.get("status") != "new"]
    learned_count = len(learned)
    m = round(sum(card["mastery"]["m"] for card in learned) / learned_count) if learned_count else None
    evidence = sum(1 for card in cards if card["mastery"]["evidence"])
    required = max(2, math.ceil(total * 0.2))
    if not learned_count:
        state = "na"
    elif m >= 80 and evidence >= required:
        state = "master"
    elif m >= 50:
        state = "progress"
    else:
        state = "weak"
    return {"m": m, "learned": learned_count, "cards_total": total,
            "coverage": round(100 * learned_count / total) if total else 0,
            "evidence_cards": evidence, "state": state,
            "state_label": LEVEL_LABELS[state]}
