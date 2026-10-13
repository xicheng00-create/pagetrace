"""入库闸门（CARD-006）：只处理批内完整重复，保留相似但不同的卡。"""
from __future__ import annotations

import re

_WS_PUNCT_RE = re.compile(r"[\s，。？！、；：,\.\?!;:'\"“”‘’()（）\[\]【】\-_/]+")


def normalize_label(s: str) -> str:
    """归一 front：小写并移除空白及常见标点。"""
    return _WS_PUNCT_RE.sub("", str(s or "").lower())


def _info_score(front: str, back: str) -> tuple[int, int]:
    alnum = len(re.findall(r"[A-Za-z0-9]", f"{front or ''}{back or ''}"))
    return alnum, len(back or "")


def _strip(e: dict) -> dict:
    return {k: v for k, v in e.items() if k != "_norm_front"}


def dedup_cards(cards: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """返回 (kept, merged_pairs, dropped)，仅完整重复触发合并或丢弃。"""
    kept: list[dict] = []
    merged: list[dict] = []
    dropped: list[dict] = []
    for card in cards:
        entry = dict(card or {})
        entry["_norm_front"] = normalize_label(entry.get("front", ""))
        same = next((old for old in kept
                     if old["concept_uid"] == entry["concept_uid"]
                     and old["_norm_front"] == entry["_norm_front"]
                     and old.get("back", "") == entry.get("back", "")), None)
        if same is not None:
            merged.append({"kept": same["front"], "merged": entry["front"], "rule": "EXACT"})
            continue
        cross = next((old for old in kept
                      if old["concept_uid"] != entry["concept_uid"]
                      and old["_norm_front"] == entry["_norm_front"]
                      and old.get("back", "") == entry.get("back", "")), None)
        if cross is not None:
            if _info_score(entry.get("front", ""), entry.get("back", "")) > _info_score(cross.get("front", ""), cross.get("back", "")):
                dropped.append({**_strip(cross), "reason": "跨概念重复"})
                kept[kept.index(cross)] = entry
            else:
                dropped.append({**card, "reason": "跨概念重复"})
            continue
        kept.append(entry)
    return [_strip(e) for e in kept], merged, dropped
