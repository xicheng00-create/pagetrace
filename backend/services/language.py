"""Deterministic card-language classification shared by quiz generation and UI contracts."""
from __future__ import annotations

CJK_RATIO_THRESHOLD = 0.20

def is_english_card(card: dict) -> bool:
    text = f"{card.get('front', '')} {card.get('back', '')}"
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    cjk = sum('一' <= c <= '鿿' for c in letters)
    return cjk / len(letters) < CJK_RATIO_THRESHOLD

def quiz_bool_options(card: dict) -> list[str]:
    return ["True", "False"] if is_english_card(card) else ["对", "错"]
