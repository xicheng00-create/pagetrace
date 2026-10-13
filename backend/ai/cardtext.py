"""考点 → 卡面文本（DESIGN_SPEC §5：question 可直接作为卡面正面）。

契约只给「考点单元」，成卡是本 app 的机械一步：
- front = question（原样，不做扩写 —— §5「不许新增事实」）
- back  = answer_points 逐条换行拼接（并集去重，顺序稳定）

本模块**不调用 LLM / 不引入第三方依赖**：成卡是可复现的确定性变换。
"""
from __future__ import annotations


def _clean_points(points) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for p in points or []:
        s = str(p).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def to_card(question: str, answer_points) -> tuple[str, str]:
    """返回 (front, back)。空 front/back 由调用方按契约违规处理。"""
    front = str(question or "").strip()
    back = "\n".join(_clean_points(answer_points))
    return front, back


def merge_points(a: list[str], b: list[str]) -> list[str]:
    """同一 concept_id 多行合并：正文 = 各行的并集（§5）。顺序 = a 在前、b 补充。"""
    return _clean_points(list(a or []) + list(b or []))
