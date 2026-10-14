"""题面文本层（QUIZ-001/003/011/012）：要点切分、是非选项、干扰项质量、提示词与产出校验。

从 `services/quizgen.py` 拆出（CLAUDE.md §3 / DESIGN_SPEC §8：后端单文件 < 300 行）。
本模块**不碰数据库**，全是「文本 → 题面」的纯函数，出题服务、一次性刷新脚本与审计共用同一口径。
"""
from __future__ import annotations

import json
import random
import re

from services import language

TYPES = ("choice", "bool")
BOOL_OPTIONS = ["对", "错"]  # 无卡上下文时的默认是非选项（兼容旧调用）

# —— QUIZ-012：干扰项可用性 ——
DISTRACTOR_MIN_CHARS = 8    # 干扰项最少字数
# 「了解（knowledge）」「关心（care）」这类「词＋括号英文」纯名词标签：不得当选项（生产已踩）
GLOSS_LABEL = re.compile(r"^[^，。；：、？！]{1,12}[（(][A-Za-z][A-Za-z0-9 .\-]*[）)]$")


def points(back: str | None) -> list[str]:
    """卡背面 → 要点列表（按行切，丢空行）。"""
    return [p.strip() for p in (back or "").split("\n") if p.strip()]


def bool_options(card: dict) -> list[str]:
    """是非题选项：语种跟随卡文（QUIZ-011）。"""
    return language.quiz_bool_options(card)


def is_gloss_label(p: str) -> bool:
    """纯名词标签（无谓语、只有「词（英文）」），不能当选项。"""
    return bool(GLOSS_LABEL.match((p or "").strip()))


def display_options(options: list[str], *, ctx: str, item_id) -> list[str]:
    """选项**呈现顺序**（QUIZ-014）：按 `(ctx, item_id)` 播种的确定性置换。

    动机（2026-10-13 owner 报障）：提示词骨架把正确项写在第一项，模型照抄
    → 生产 76 题里 72 题（94.7%）正确答案都在首位，等于白送。本函数在
    **交付前端的唯一出口**打乱顺序，保证位置近似均匀：
    - **不改库**：`quiz_items.options` 原样保留，缓存复用与幂等不受影响；
    - **不改判分**：QUIZ-004 仍按**文本**比对，`answer_key` 仍不下发（QUIZ-001）；
    - **同一 ctx（会话 id）同一题恒定** → 结果页能复现用户当时看到的顺序；
    - **不同会话重新置换** → 位置记不住。
    """
    opts = [str(o) for o in (options or [])]
    if len(opts) < 2:
        return opts
    order = list(range(len(opts)))
    random.Random(f"{ctx}|{item_id}|options").shuffle(order)
    return [opts[i] for i in order]


def usable_distractor(p: str, correct: str) -> bool:
    """能否当干扰项：够长、≠正确答案、且不是纯名词标签。"""
    p = (p or "").strip()
    if len(p) < DISTRACTOR_MIN_CHARS or p == correct:
        return False
    return not is_gloss_label(p)


def pick_distractors(pool: list[str], correct: str, card_id: int, k: int = 2) -> list[str]:
    """从同章要点池取 k 条干扰项：先挑「与正确答案长度相近」的候选，再按 `card_id` 确定性抽签。

    旧实现 `pool[:2]` 恒取池首两条 → 同章每道题的干扰项完全相同（生产实测：第 1 章所有选择题的
    干扰项恒为卡 194 的「了解（knowledge）」「关心（care）」）。抽签用 `card_id` 播种 → 同库同卡
    结果稳定（幂等，缓存可复用），不同卡结果不同。
    """
    cand = [p for p in pool if usable_distractor(p, correct)]
    if len(cand) <= k:
        return cand
    cand = sorted(cand, key=lambda p: (abs(len(p) - len(correct)), p))
    head = cand[: max(k * 4, 8)]
    return sorted(random.Random(f"{card_id}|distractor").sample(head, k))


def choice_example(c: dict) -> dict:
    # 骨架只示范**形状**：三条选项文字同形、answer_key 不落在固定位置，避免模型照抄
    # 「正确项永远第一项」（2026-10-13 报障的根因，见 QUIZ-014）。
    return {"card_id": c["card_id"], "type": "choice", "stem": "…？",
            "options": ["（完整说法·甲）", "（完整说法·乙）", "（完整说法·丙）"],
            "answer_key": "（与正确那条逐字相同，位置任意）"}


def bool_example(c: dict) -> dict:
    opts = bool_options(c)
    return {"card_id": c["card_id"], "type": "bool", "stem": "…", "options": opts, "answer_key": opts[0]}


def system_prompt(cards: list[dict], types: list[str]) -> str:
    """提示词（QUIZ-012）：**按题型分别给规则 + 同型 JSON 骨架**，且逐卡声明 `want`。

    旧版骨架写死 `{"type":"bool", …}` 且规则只讲判断题 → 模型照抄样例，要选择题也返 `type=bool`，
    被 `validate` 拒收 → 整章选择题全部降级为机械题（生产实测 2026-09-27 起 28/30 道选择题均如此，
    见 `reports/quiz-fallback-2026-10-03.md`）。
    """
    ctx = [{"card_id": c["card_id"], "question": c["front"], "answer_points": points(c.get("back")),
            "want": t, "bool_options": bool_options(c)} for c, t in zip(cards, types, strict=True)]
    if all(language.is_english_card(c) for c in cards):
        rules = (
            "You are a study app quiz author. Use only the supplied key points; never introduce outside facts.\n"
            "Each card carries a `want` field naming the required question type — obey it literally "
            "(want=choice → a choice question; want=bool → a true/false question). Never switch types.\n"
            "- want=choice: the stem asks about ONE specific key point of that card (end with '?'), not a generic "
            "\"which of these belongs to…\"; 3–4 options, each a FULL statement or definition copied from the key "
            "points (never a bare label like \"care (care)\"); exactly one option is correct and verbatim equal to a "
            "key point, the others are plausible statements from other cards of the same chapter; answer_key must "
            "equal one option verbatim.\n"
            "- want=bool: the stem is a single proposition; options must equal that card's bool_options verbatim; "
            "answer_key must equal one of them verbatim.\n")
    else:
        rules = (
            "你是复习 app 的出题员。仅依据给出的考点出题，不得引入卡外事实。\n"
            "每张卡带 `want` 字段指定该卡的题型，**必须逐字照办**（want=choice → 出选择题；want=bool → 出是非题），"
            "不得自行更换题型。\n"
            "- want=choice（选择题）：题干**针对该卡一条具体考点**提问（以「？」结尾，如「安全型依恋的婴儿会发展出什么预期？」），"
            "**不要**用「以下哪一项属于…」「下列哪项正确」这类泛问；给 3–4 个选项，**每个选项都是一句完整说法/定义**"
            "（至少 8 字，**不得是「了解（knowledge）」这类纯名词标签**）；恰有一个选项正确且与该卡考点逐字一致，"
            "其余选项取自同章其他卡的考点、似是而非；answer_key 必须逐字等于某个选项。\n"
            "**选项顺序不得固定：正确答案可位于任意位置，禁止总放在第一项。**\n"
            "- want=bool（是非题）：题干一句命题；options 必须**逐字**等于该卡 bool_options；"
            "answer_key 必须逐字等于其中之一。\n")
    pairs = list(zip(cards, types, strict=True))
    examples = [bool_example(next(c for c, t in pairs if t == "bool")) if t == "bool"
                else choice_example(next(c for c, t in pairs if t == "choice"))
                for t in dict.fromkeys(types)]  # 去重保序：每种题型各给一个同型样例
    skeleton = json.dumps({"items": examples}, ensure_ascii=False)
    return (rules + f"\n只输出 JSON，骨架如下（items 里的 type/options/answer_key 按各卡 want 填写）：\n"
            f"{skeleton}\n\n考点：\n" + json.dumps(ctx, ensure_ascii=False))


def validate(item: dict | None, want: str, expected_options: list[str] | None = None) -> dict | None:
    """校验 LLM 产出：类型 = want、stem 非空、options ≥2、answer_key 逐字命中选项。"""
    if not isinstance(item, dict):
        return None
    expected_options = expected_options or BOOL_OPTIONS
    t = item.get("type")
    if t != want or t not in TYPES:
        return None
    stem = str(item.get("stem") or "").strip()
    options = [str(o).strip() for o in (item.get("options") or []) if str(o).strip()]
    key = str(item.get("answer_key") or "").strip()
    if not stem or len(options) < 2 or not key or key not in options:
        return None
    if t == "bool" and (len(options) != 2 or options != expected_options):
        return None
    return {"type": t, "stem": stem, "options": options, "answer_key": key, "source": "ai"}
