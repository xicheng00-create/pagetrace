"""卡片 / 概念关键词检索（数据源 = `cards` + `concepts`；不引向量库、不装依赖）。

**口径与参考实现同源**：`pagetrace/AI学习小组app/backend/ai/rag.py` 的中文 2-gram 分词 +
「query 命中比例」打分 —— `score = |query词集 ∩ 文档词集| / |query词集|`，两者逐字一致
（停用词、`len > 1` 过滤都一样）。换的只是检索单元：`chunks` → `cards` / `concepts`。

并列处理（参考实现没有，本层补上并写明理由）：命中的词越稀有越说明「这条不是偶然撞上的」，
所以同分时按命中词的 IDF 之和（纯词频计数，无新依赖、无模型）高者优先；再并列按 id 升序。
没有这一层，同分次序由 SQLite 行序决定 —— 同一 query 两次可能给出不同 top-k，验收不可复现。

卡池 SQL 不在这里写：卡片的读取入口只有 `services.card_quiz_pool`（UP-006 单点），
本层只做分词与排序，范围（同户 + 已解锁章）由那个入口保证。
"""
from __future__ import annotations

import math
import re

from services import card_quiz_pool

from ai import tutor_synonyms

# 弱命中阈值（规格 §9e）：主臂 top1 覆盖率低于此值 = 「2-gram 只是偶然撞上」，
# 不硬答，改走澄清反问。这是口径常量，不是魔法调参——换值必须同步改
# DESIGN_SPEC REQ-TUTOR-06 与 tests/test_tutor_clarify.py 的断言。
WEAK_COVERAGE = 0.5

# 澄清选项口径（规格 §9e）：3–5 个、去重、按重叠数降序；不足 3 个就不反问。
CLARIFY_MIN_OPTIONS = 3
CLARIFY_MAX_OPTIONS = 5

# 中文按 2-gram、英文按词切分（停用词与参考实现同一份）
_STOPWORDS = {"的", "了", "是", "在", "我", "你", "他", "她", "它", "吗", "呢", "什么",
              "怎么", "为什么", "如何", "请", "个", "这", "那", "和", "与", "或"}

_CONCEPT_SQL = (
    "SELECT cp.id AS concept_id, cp.name AS concept_name, COALESCE(cp.tags,'') AS tags,"
    " ch.id AS chapter_id, ch.name AS chapter_name"
    " FROM concepts cp JOIN chapters ch ON ch.id=cp.chapter_id"
    " JOIN books b ON b.id=ch.book_id"
    " WHERE b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id="
    "(SELECT u1.household_id FROM users u1 WHERE u1.id=?))"
    " AND (? IS NULL OR b.subject_id=?) AND (? IS NULL OR ch.id=?)"
)


class CardNotFound(LookupError):
    """卡片不存在，或不在该登录用户可见范围（两者对外一律 404，不泄露存在性）。"""


def _tokens(text: str) -> set[str]:
    """2-gram 词集（逐字照抄参考实现，含 `len > 1` 过滤——单字不进 key）。"""
    text = (text or "").lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    for seg in re.findall(r"[一-鿿]+", text):
        if len(seg) == 1:
            words.add(seg)
        else:
            for i in range(len(seg) - 1):
                words.add(seg[i:i + 2])
    return {w for w in words if w and w not in _STOPWORDS and len(w) > 1}


def _unit_text(parts) -> set[str]:
    return _tokens(" ".join(part or "" for part in parts))


def _rank(query_tokens: set[str], units: list[tuple[dict, set[str]]], top_k: int) -> list[dict]:
    """打分 + 定序。units = [(行, 文档词集)]。

    主分 = 参考实现口径（query 命中比例）；同分用 IDF 稀有权重定序，再按 id 升序兜底。
    """
    if not query_tokens or not units or top_k <= 0:
        return []
    df: dict[str, int] = {}
    for _row, tokens in units:
        for token in tokens:
            df[token] = df.get(token, 0) + 1
    total = len(units)

    def idf(token: str) -> float:
        return math.log((total + 1) / (df.get(token, 0) + 0.5))

    q_weight = sum(idf(token) for token in query_tokens) or 1.0
    scored = []
    for row, tokens in units:
        overlap = query_tokens & tokens
        if not overlap:
            continue
        score = len(overlap) / len(query_tokens)
        rarity = sum(idf(token) for token in overlap) / q_weight
        scored.append((round(score, 4), round(rarity, 6), row))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]["id"]))
    return [dict(row, score=score) for score, _rarity, row in scored[:top_k]]


def _cards_units(con, user_id, subject_id=None, chapter_id=None) -> list[tuple[dict, set[str]]]:
    """检索单元 = 卡片问句 + 子卡标题 + 概念名 + 标签 + 答案（范围/租户由卡池单点保证）。

    概念名/标签进单元的理由：卡片问句常是「X 是什么？」，只有概念名带出 X，
    不带上就永远检索不到概念（规格 §9 口径坑：两张表都要覆盖）。
    """
    rows = card_quiz_pool.retrieval_cards(con, user_id, subject_id, chapter_id).fetchall()
    return [
        ({"id": row["card_id"], "card_id": row["card_id"], "concept_id": row["concept_id"],
          "concept_name": row["concept_name"], "chapter_id": row["chapter_id"],
          "chapter_name": row["chapter_name"], "front": row["front"], "back": row["back"],
          "title": row["title"]},
         _unit_text((row["front"], row["title"], row["concept_name"], row["tags"], row["back"])))
        for row in rows
    ]


def _alias_tokens(query: str) -> set[str]:
    """口语键 → 术语片段 → 2-gram 词集（别名值也要过分词，否则永远命不中）。"""
    targets = tutor_synonyms.expand(query)
    tokens: set[str] = set()
    for target in sorted(targets):
        tokens |= _tokens(target)
    return tokens


def pick(con, query: str, *, user_id, subject_id=None, chapter_id=None,
         top_k: int = 5) -> dict:
    """两臂检索 + 弱命中判定（规格 §9e）。返回的 `weak` 供上层决定是否澄清反问。

    - 主臂：2-gram 覆盖率（口径未改）。
    - 别名臂：只在主臂弱（< `WEAK_COVERAGE`）时启用；命中卡的 `via="alias"` 排在前面，
      主臂结果原样附后并标 `via="exact"` —— 别名表只当兜底，不再替用户硬答。
    - `options`：主臂弱时给出的澄清候选概念（3–5 个，不足 3 个上层就不反问）。
    """
    units = _cards_units(con, user_id, subject_id, chapter_id)
    query_tokens = _tokens(query)
    primary = [dict(hit, via="exact") for hit in _rank(query_tokens, units, top_k)]
    top_coverage = float(primary[0]["score"]) if primary else 0.0

    alias_hits: list[dict] = []
    if top_coverage < WEAK_COVERAGE:
        alias_query = _alias_tokens(query)
        if alias_query:
            alias_hits = [dict(hit, via="alias") for hit in _rank(alias_query, units, top_k)]

    if alias_hits:
        merged, seen = [], set()
        for hit in alias_hits + primary:
            if hit["card_id"] in seen:
                continue
            seen.add(hit["card_id"])
            merged.append(hit)
        cards = merged[:top_k]
    else:
        cards = primary

    weak = top_coverage < WEAK_COVERAGE
    return {
        "cards": cards,
        "primary": primary,
        "alias_hits": alias_hits,
        "top_coverage": top_coverage,
        "weak": weak,
        "options": (concept_options(con, query, user_id=user_id, subject_id=subject_id,
                                    chapter_id=chapter_id, cards=alias_hits)
                    if weak else []),
    }


def retrieve_cards(con, query: str, *, user_id, subject_id=None, chapter_id=None,
                   top_k: int = 5) -> list[dict]:
    """按 query 取 top-k 卡（两臂合并后的结果，带 `via`）。"""
    return pick(con, query, user_id=user_id, subject_id=subject_id,
                chapter_id=chapter_id, top_k=top_k)["cards"]


def concept_options(con, query: str, *, user_id, subject_id=None, chapter_id=None,
                    cards=None, limit: int = CLARIFY_MAX_OPTIONS) -> list[dict]:
    """澄清候选：与 query 有任意 2-gram 重叠的概念名，按重叠数降序、去重、截 limit。

    另加一路：别名臂命中卡所属的概念 —— 口语问句与概念名一个词都不重叠时
    （「他动手了我怕他」 vs 「亲密伴侣暴力」），只有别名表把口语搬到术语上才够得着。
    """
    query_tokens = _tokens(query)
    alias_tokens = _alias_tokens(query)
    scored, seen = [], set()
    rows = con.execute(
        _CONCEPT_SQL, (user_id, subject_id, subject_id, chapter_id, chapter_id)).fetchall()
    for row in rows:
        tokens = _unit_text((row["concept_name"], row["tags"], row["chapter_name"]))
        overlap = len(query_tokens & tokens) or len(alias_tokens & tokens)
        if not overlap:
            continue
        seen.add(row["concept_id"])
        scored.append((overlap, row["concept_id"], row["concept_name"]))
    for card in cards or []:
        concept_id = card.get("concept_id")
        if concept_id is None or concept_id in seen:
            continue
        seen.add(concept_id)
        name = card.get("concept_name") or ""
        bridge = len(alias_tokens & _unit_text((name,)))
        scored.append((max(bridge, 1), concept_id, name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [{"concept_id": concept_id, "name": name}
            for _overlap, concept_id, name in scored[:limit]]


def retrieve_concepts(con, query: str, *, user_id, subject_id=None, chapter_id=None,
                      top_k: int = 3) -> list[dict]:
    """按 query 取 top-k 概念（检索单元 = 概念名 + 标签 + 章名）。"""
    rows = con.execute(
        _CONCEPT_SQL, (user_id, subject_id, subject_id, chapter_id, chapter_id)).fetchall()
    units = [
        ({"id": row["concept_id"], "concept_id": row["concept_id"],
          "name": row["concept_name"], "chapter_id": row["chapter_id"],
          "chapter_name": row["chapter_name"]},
         _unit_text((row["concept_name"], row["tags"], row["chapter_name"])))
        for row in rows
    ]
    return _rank(_tokens(query), units, top_k)


def retrieve(con, query: str, *, user_id, subject_id=None, chapter_id=None,
             top_k: int = 5, concept_k: int = 3) -> dict:
    """一次拿两表：{"cards": [...], "concepts": [...]}。无 query 或全不命中 → 空列表（触发兜底）。"""
    return {
        "cards": retrieve_cards(con, query, user_id=user_id, subject_id=subject_id,
                                chapter_id=chapter_id, top_k=top_k),
        "concepts": retrieve_concepts(con, query, user_id=user_id, subject_id=subject_id,
                                      chapter_id=chapter_id, top_k=concept_k),
    }


def card_by_id(con, card_id, *, user_id) -> dict:
    """取单张卡原文（贴卡讲解场景）；不可见即 CardNotFound —— 与检索同一套可见范围。"""
    row = card_quiz_pool.retrieval_card(con, card_id, user_id)
    if row is None:
        raise CardNotFound("card not found")
    return dict(row)


_CONCEPT_BY_ID_SQL = (
    "SELECT cp.id AS concept_id, cp.name AS concept_name, COALESCE(cp.tags,'') AS tags,"
    " ch.id AS chapter_id, ch.name AS chapter_name"
    " FROM concepts cp JOIN chapters ch ON ch.id=cp.chapter_id"
    " JOIN books b ON b.id=ch.book_id"
    " WHERE cp.id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id="
    "(SELECT u1.household_id FROM users u1 WHERE u1.id=?))"
)


class ConceptNotFound(LookupError):
    """概念不存在，或不在该登录用户可见范围（对外一律 404，不泄露存在性）。"""


def concept_by_id(con, concept_id, *, user_id) -> dict:
    row = con.execute(_CONCEPT_BY_ID_SQL, (concept_id, user_id)).fetchone()
    if row is None:
        raise ConceptNotFound("concept not found")
    return dict(row)


def cards_of_concept(con, concept_id, *, user_id, top_k: int = 5) -> list[dict]:
    """澄清点选后：直接在该概念下取卡（跳过检索，规格 §9e）。

    走卡池单点 `retrieval_cards` 再按 concept_id 过滤 —— 不新增第二套范围 SQL。
    概念下没有卡时返回空列表，由上层回「库里没找到贴合的页」。
    """
    rows = card_quiz_pool.retrieval_cards(con, user_id).fetchall()
    cards = [
        {"card_id": row["card_id"], "concept_id": row["concept_id"],
         "concept_name": row["concept_name"], "chapter_id": row["chapter_id"],
         "chapter_name": row["chapter_name"], "front": row["front"], "back": row["back"],
         "title": row["title"], "score": 1.0, "via": "concept"}
        for row in rows if row["concept_id"] == concept_id
    ]
    cards.sort(key=lambda card: card["card_id"])
    return cards[:top_k]

