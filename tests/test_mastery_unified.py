"""MAST-001 / MAST-006：UNI-MASTER 唯一计算点 —— 卡级公式、7 天半衰期、层级四态阈值、**跨 app 一致**。

跨 app 一致性是红线：同一份作答在个人复习 app 与 AI 学习小组 app 必须得出同一个 `m` 与同一个四态。
因此本文件不仅测本 app 的 `services/mastery.py`，还**逐字比对** AI 学习小组的公式常数。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from services import mastery as M  # noqa: E402

AI_MASTERY = Path("./optional-private-reference")
BASE = "2026-09-27T12:00:00+08:00"


def _ev(days_ago: float, earned=None, points=None) -> dict:
    """以 BASE 为基准造一条作答事件（时间固定 → 衰减可精确断言）。"""
    at = datetime.fromisoformat(BASE) - timedelta(days=days_ago)
    ev: dict = {"created_at": at.isoformat()}
    if earned is not None:
        ev["earned"] = earned
    if points is not None:
        ev["points"] = points
    return ev


def test_state_scores_and_level_labels_are_single_source():
    assert M.STATE_SCORES == {"new": 0, "learning": 40, "reviewing": 70, "mastered": 100}
    assert M.LEVEL_LABELS == {"master": "已掌握", "progress": "进行中", "weak": "薄弱", "na": "未评估"}


def test_no_evidence_falls_back_to_state_score():
    """无作答证据：`acc = None` → `m = 状态分`（不是 0，也不用练习分冒充）。"""
    for status, expected in (("new", 0), ("learning", 40), ("reviewing", 70), ("mastered", 100)):
        card = M.card_mastery(status, [])
        assert (card["m"], card["acc"], card["evidence"]) == (expected, None, False)


def test_card_formula_is_half_state_half_accuracy():
    hit = M.card_mastery("learning", [_ev(0, earned=1)], at=BASE)
    assert (hit["acc"], hit["m"], hit["evidence"]) == (100, 70, True)
    half = M.card_mastery("new", [_ev(0, earned=1), _ev(0, earned=0)], at=BASE)
    assert (half["acc"], half["m"]) == (50, 25)


def test_decay_is_seven_day_half_life():
    seven = M.card_mastery("new", [_ev(7, earned=0), _ev(0, earned=1)], at=BASE)
    assert seven["acc"] == 67                      # 权重 0.5 / 1.0 → 1/1.5
    thirty = M.card_mastery("new", [_ev(30, earned=0), _ev(0, earned=1)], at=BASE)
    assert thirty["acc"] == 95                     # 30 天前几乎归零


def test_events_without_timestamp_are_skipped_and_defaults_are_safe():
    card = M.card_mastery("learning", [{"earned": 1}, _ev(0, earned=None, points=None)], at=BASE)
    assert card["acc"] == 0                        # 唯一带时间的作答未得分 → 0%（不是 None）
    assert card["evidence"] is True


def test_level_mastery_rollup_and_coverage():
    def card(status, m, evidence):
        return {"status": status, "mastery": {"m": m, "evidence": evidence}}

    assert M.level_mastery([]) == {"m": None, "learned": 0, "cards_total": 0, "coverage": 0,
                                   "evidence_cards": 0, "state": "na", "state_label": "未评估"}
    got = M.level_mastery([card("mastered", 100, True), card("mastered", 100, True), card("new", 0, False)])
    assert (got["m"], got["learned"], got["cards_total"], got["coverage"]) == (100, 2, 3, 67)
    assert (got["state"], got["state_label"]) == ("master", "已掌握")
    assert got["evidence_cards"] == 2


def test_master_requires_min_evidence_even_with_perfect_m():
    def card(status, m, evidence):
        return {"status": status, "mastery": {"m": m, "evidence": evidence}}

    # m = 87 ≥ 80，但证据卡 1 < max(2, ceil(3×0.2)=1)=2 → 只能「进行中」（不得冒充已掌握）
    thin = M.level_mastery([card("mastered", 100, True), card("mastered", 100, False),
                            card("reviewing", 60, False)])
    assert (thin["m"], thin["evidence_cards"], thin["state"]) == (87, 1, "progress")
    # 集合越小，20% 下界越被 max(2, …) 兜住：4 张卡里 1 张有证据仍不够
    small = M.level_mastery([card("mastered", 100, True)] + [card("mastered", 100, False)] * 3)
    assert (small["evidence_cards"], small["state"]) == (1, "progress")
    # 证据达标 → 已掌握
    ok = M.level_mastery([card("mastered", 100, True), card("mastered", 100, True),
                          card("mastered", 100, False)])
    assert ok["state"] == "master"


def test_weak_and_progress_thresholds():
    def card(m):
        return {"status": "learning", "mastery": {"m": m, "evidence": True}}

    assert M.level_mastery([card(40)])["state"] == "weak"
    assert M.level_mastery([card(50)])["state"] == "progress"


@pytest.mark.skipif(not AI_MASTERY.exists(), reason="AI 学习小组 app 不在本机")
def test_formula_parity_with_ai_study_app():
    """两 app 同一常数（半衰期 7 天）、同一阈值（≥80 且证据 ≥ max(2, 20%)）、同一证据口径（≥1 次）。"""
    ai = AI_MASTERY.read_text(encoding="utf-8")
    assert "0.5 ** (days / 7)" in ai
    assert "evidence_cards >= max(2, math.ceil(cards_total * 0.2))" in ai
    assert '"evidence": count > 0' in ai
    mine = (BACKEND / "services" / "mastery.py").read_text(encoding="utf-8")
    assert "0.5 ** (days / 7)" in mine
    assert "max(2, math.ceil(total * 0.2))" in mine
    assert "len(events) > 0" in mine
