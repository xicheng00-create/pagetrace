"""CARD-006 入库闸门：只处理完整重复，保留相似但不同的卡。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from ai import cardgate  # noqa: E402


def _card(uid, front, back, points=None):
    return {"concept_uid": uid, "front": front, "back": back, "answer_points": points or [back]}


def test_same_concept_exact_dup_merged():
    cards = [_card("A", "什么是供需分析？", "分析供给与需求"), _card("A", "什么是供需分析！", "分析供给与需求")]
    kept, merged, dropped = cardgate.dedup_cards(cards)
    assert len(kept) == 1 and len(merged) == 1 and dropped == []


def test_same_concept_similar_is_kept():
    cards = [_card("A", "供需分析是什么？", "分析供需"), _card("A", "供需分配是什么？", "配置供需")]
    kept, merged, dropped = cardgate.dedup_cards(cards)
    assert len(kept) == 2 and merged == [] and dropped == []


def test_cross_concept_exact_dup_dropped():
    cards = [_card("A", "什么是预热步骤？", "照料者作为出发点"), _card("B", "什么是预热步骤！", "照料者作为出发点")]
    kept, merged, dropped = cardgate.dedup_cards(cards)
    assert len(kept) == 1 and len(dropped) == 1 and dropped[0]["reason"] == "跨概念重复"


def test_cross_concept_similar_is_kept():
    cards = [_card("A", "项目赞助人与干系人是什么关系？", "答案甲"), _card("B", "项目赞助人与干系人是什么职责？", "答案乙")]
    kept, merged, dropped = cardgate.dedup_cards(cards)
    assert len(kept) == 2 and dropped == []


def test_normalize_helper():
    assert cardgate.normalize_label(" 冲煮，变量！ ") == "冲煮变量"
    assert cardgate.normalize_label(None) == ""
