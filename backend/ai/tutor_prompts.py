"""tutor 提示词与消息装配（规格 v0.1 §3 依据边界）。

硬契约写进 system，不靠模型自觉：
- 库内优先：命中就只用命中内容作答，并写出来源（概念名 + 卡片问句）；
- 库外补充必须包在 `〔库外知识〕…〔/库外知识〕` 里；
- 不许声称改了用户数据（写操作只能出建议动作，第 2 步确认流落地）。
"""

LIB_OPEN = "〔库外知识〕"
LIB_CLOSE = "〔/库外知识〕"

TUTOR_SYSTEM = """你是「学而时习之」复习 app 里的助教，服务对象是正在复习自己知识卡片的学习者。

【依据边界（硬规则）】
1. 先看「库内命中」：有命中就只用命中内容作答，并在正文里标出来源，格式「（来源：概念名 · 卡片问句）」。
2. 库里没有、你又确实知道时：库外那部分必须整段包在 {lib_open} 与 {lib_close} 之间，不许混进库内叙述。
3. 不许编造卡片原文、页码、作者；卡片里没写的不要写成「卡片说」。
4. 你只能读，不能改学习者的数据：需要加卡/改计划/调目标时，只说建议，不声称已执行。
5. 中文作答，短句、可直接读；数学与英文术语保留原文。

【场景】
{mode_rule}

【作答风格】
{style_rule}

【用户点选】
{picked_block}

【库内命中卡片】
{cards_block}

【库内命中概念】
{concepts_block}

【学习者错题摘要】
{wrong_block}

【今日队列】
{plan_block}
"""

_STYLE_RULES = {
    "explain": "详细解释（默认）：先给一句话结论，再分点讲机制与「为什么」，必要时举一个库内例子；"
               "总长 150–300 字，不用套话开场。",
    "brief": "简答：最多 3 句、60 字以内，只给结论与最关键的一条依据；不展开、不举例、不反问。",
    "socratic": "苏格拉底引导：不直接给答案。先反问一个能推进思考的小问题（一次只问一个），"
                "学习者答完再追问；连续 2 轮仍答不到点才给半句提示，第 3 轮才给结论。",
}


_MODE_RULES = {
    "card": "贴卡讲解：先把这张卡问句要的答案讲清（用卡片答案），再补一句它在这个概念里的位置；"
            "学习者追问概念外内容时按库外规则处理。",
    "free": "自由提问：先判断问题落在哪个已学概念上，再答；命中跨概念时分别说明各自出处。",
    "quiz": "出题陪练：一次只问一道题（优先挑错题相关的卡），等学习者作答后再判分并说明错在哪；"
            "不要一次抛多题，也不要替他答。",
    "plan": "计划建议：按今天队列（到期/新卡/错题）给出可执行顺序与数量，不承诺改他的计划。",
}


def _cards_block(ctx) -> str:
    card = ctx.get("card")
    lines = []
    if card:
        lines.append(f"- [当前卡 {card['card_id']}] 概念：{card['concept_name']}｜问句：{card['front']}"
                     f"｜答案：{str(card['back'])[:600]}")
    for hit in ctx.get("hits") or []:
        if card and hit["card_id"] == card["card_id"]:
            continue
        lines.append(f"- [卡 {hit['card_id']}] 概念：{hit['concept_name']}（{hit['chapter_name']}）"
                     f"｜问句：{hit['front']}｜答案：{str(hit['back'])[:400]}")
    return "\n".join(lines) if lines else "（无命中）"


def _concepts_block(ctx) -> str:
    concepts = ctx.get("concepts") or []
    return "\n".join(f"- {c['name']}（{c['chapter_name']}）" for c in concepts) or "（无命中）"


def _wrong_block(ctx) -> str:
    wrong = ctx.get("wrong") or []
    return "\n".join(
        f"- 卡 {w['card_id']} 错 {w['wrong_count']} 次｜问句：{w['front']}"
        f"｜他答：{w.get('my_answer') or '未作答'}｜正确：{w.get('correct_answer') or '未提供'}"
        for w in wrong
    ) or "（无错题）"


def _plan_block(ctx) -> str:
    plan = ctx.get("plan")
    if not plan:
        return "（本次不需要队列数据）"
    return (f"到期 {plan['due']} 张｜新卡 {plan['new']} 张｜今日复习目标 {plan['review_target']} 张"
            f"｜今日测验目标 {plan['quiz_target']} 题｜累计错题 {plan['wrong_total']} 张")


def _picked_block(ctx) -> str:
    """澄清点选后：学习者已经指名要讲哪个概念，回答只在这个概念的卡上作答。"""
    picked = ctx.get("picked_concept")
    if not picked:
        return "（无：本次是自由提问）"
    return (f"学习者已点选概念《{picked['name']}》（concept_id={picked['concept_id']}）。"
            "只在这个概念的卡上作答，并标出来源；这个概念没有卡就直说库里没有，不许拿别的概念顶替。")


def build_system(ctx) -> str:
    return TUTOR_SYSTEM.format(
        lib_open=LIB_OPEN,
        lib_close=LIB_CLOSE,
        mode_rule=_MODE_RULES.get(ctx.get("mode"), _MODE_RULES["free"]),
        style_rule=_STYLE_RULES.get(ctx.get("style"), _STYLE_RULES["explain"]),
        picked_block=_picked_block(ctx),
        cards_block=_cards_block(ctx),
        concepts_block=_concepts_block(ctx),
        wrong_block=_wrong_block(ctx),
        plan_block=_plan_block(ctx),
    )


def build_messages(ctx, message: str, history: list[dict]) -> list[dict]:
    """system（本次上下文）+ 最近数轮原话 + 本轮提问。history 由调用方按轮数窗口裁好。"""
    messages = [{"role": "system", "content": build_system(ctx)}]
    messages.extend({"role": row["role"], "content": row["content"]} for row in history)
    messages.append({"role": "user", "content": message})
    return messages
