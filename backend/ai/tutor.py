"""tutor 编排（第 1 步：非流式）。四场景走内部 intent：card / free / quiz / plan。

职责边界（规格 v0.1 §3/§7）：
- **只写自己三张表**（conversations / messages / quota_usage）；不写 cards / card_reviews / prefs，
  加卡改计划只能出「建议动作」，由第 2 步的确认流落地。
- 模型不可用（无 key / 超时 / 报错）时不抛 500：退成「只给库内原文」的答复，并标记 fallback=True。
- 会话按 `user_id` 归属；别人的 conversation_id 一律 ConversationNotFound（对外 404）。
"""
from __future__ import annotations

from config import BaseConfig
from flask import current_app, has_app_context
from services import clock, llm

from ai import rag, tutor_context, tutor_prompts
from ai.rag import CardNotFound, ConceptNotFound  # noqa: F401 （API 层按此转 404）

MODES = ("card", "free", "quiz", "plan")
STYLES = ("explain", "brief", "socratic")
MESSAGE_MAX = 4000
CARD_DEFAULT_MESSAGE = "讲讲这张卡"  # mode=card 且没带 message 时的默认问法（贴卡讲解不用先打字）
SOURCES_MAX = 3

# 澄清反问（规格 §9e）。CLARIFY_PREFIX 是落库标记：会话里靠它数「连续澄清了几次」，
# 不改表结构（messages.role 只有 user / assistant 两值）。
CLARIFY_QUESTION = "你说的是哪一种？"
CLARIFY_PREFIX = "〔澄清〕"
CLARIFY_MAX_ROUNDS = 2      # 连续两次澄清仍选不出 → 直说库里没有（A10）
CLARIFY_MIN_OPTIONS = rag.CLARIFY_MIN_OPTIONS
CLARIFY_MAX_OPTIONS = rag.CLARIFY_MAX_OPTIONS
NOT_FOUND_REPLY = "库里没找到贴合的页。换个更具体的说法，或者先告诉我在读哪一章，我再找。"
CLARIFY_PICK_MESSAGE = "就讲这个概念"  # 点选后重发时可只带 concept_id，不带整句


class ConversationNotFound(LookupError):
    """会话不存在、已删除，或不属于该登录用户（对外一律 404）。"""


def _cfg(key, default):
    if has_app_context():
        return current_app.config.get(key, default)
    return getattr(BaseConfig, key, default)


def _title(message: str) -> str:
    return (message or "").strip()[:30] or "新对话"


def load_conversation(con, user_id, conversation_id):
    row = con.execute(
        "SELECT id,user_id,title,summary,created_at,updated_at FROM conversations"
        " WHERE id=? AND user_id=? AND deleted_at IS NULL",
        (conversation_id, user_id),
    ).fetchone()
    if row is None:
        raise ConversationNotFound("conversation not found")
    return row


def create_conversation(con, user_id, title):
    at = clock.now_iso()
    cur = con.execute(
        "INSERT INTO conversations(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
        (user_id, title, at, at),
    )
    return load_conversation(con, user_id, cur.lastrowid)


def history(con, conversation_id, rounds=None) -> list[dict]:
    """最近 N 轮原话（1 轮 = user + assistant）。先取最新 N*2 条再翻回时序。"""
    rounds = int(rounds or _cfg("TUTOR_HISTORY_ROUNDS", 6))
    rows = con.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conversation_id, max(rounds, 0) * 2),
    ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def messages(con, conversation_id) -> list[dict]:
    rows = con.execute(
        "SELECT id, role, content, tokens_in, tokens_out, created_at FROM messages"
        " WHERE conversation_id=? ORDER BY id ASC",
        (conversation_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def build(con, user_id, *, mode, message, card_id=None, subject_id=None, chapter_id=None,
          concept_id=None, conversation=None, style="explain") -> dict:
    """装配上下文 + 判定是否需要澄清反问（结果挂在 `ctx["clarify"]`）。"""
    ctx = tutor_context.gather(con, user_id, mode=mode, message=message, card_id=card_id,
                               subject_id=subject_id, chapter_id=chapter_id, concept_id=concept_id)
    ctx["style"] = style
    ctx["clarify"] = _decide_clarify(con, ctx, mode, conversation)
    return ctx


def clarify_rounds(con, conversation_id) -> int:
    """本会话末尾连续「澄清」回合数（0 = 上一句是正常回答，或还没问过）。

    序列 `u, a(〔澄清〕…), u, a(〔澄清〕…)` 数出 2；中间夹一次正常回答即归零。
    """
    if not conversation_id:
        return 0
    rows = con.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 12",
        (conversation_id,),
    ).fetchall()
    rounds = 0
    for row in rows:
        content = str(row["content"] or "")
        if row["role"] == "assistant" and content.startswith(CLARIFY_PREFIX):
            rounds += 1
        elif row["role"] == "user":
            continue  # 澄清的问答成对出现，用户那句是澄清的一部分
        else:
            break
    return rounds


def _decide_clarify(con, ctx, mode, conversation):
    """弱命中判定（规格 §9e）。返回 None = 正常作答；否则给出澄清内容。

    条件：mode=free（card 自带卡；quiz/plan 是操作指令，不是内容检索）、
    非点选回合、主臂 top1 覆盖率 < 0.5、候选概念 ≥3 个。
    连续 `CLARIFY_MAX_ROUNDS` 次仍没点选 → exhausted，改用「库里没找到贴合的页」。
    """
    if mode != "free" or ctx.get("picked_concept"):
        return None
    retrieval = ctx.get("retrieval") or {}
    if not retrieval.get("weak"):
        return None
    rounds = clarify_rounds(con, conversation["id"]) if conversation else 0
    if rounds >= CLARIFY_MAX_ROUNDS:
        return {"exhausted": True, "question": None, "options": [], "rounds": rounds}
    options = (retrieval.get("options") or [])[:CLARIFY_MAX_OPTIONS]
    if len(options) < CLARIFY_MIN_OPTIONS:
        return None  # 选项不足 3 个：不反问，按原来的兜底回答走
    return {"exhausted": False, "question": CLARIFY_QUESTION, "options": options, "rounds": rounds}


def _record_turn(con, conv, user_id, message, text, tokens_in=None, tokens_out=None):
    """一次问答落库：user + assistant 两条一次事务，不留半截；返回 assistant 消息 id。"""
    at = clock.now_iso()
    con.execute(
        "INSERT INTO messages(conversation_id,role,content,tokens_in,tokens_out,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (conv["id"], "user", message, tokens_in, None, at),
    )
    cur = con.execute(
        "INSERT INTO messages(conversation_id,role,content,tokens_in,tokens_out,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (conv["id"], "assistant", text, None, tokens_out, at),
    )
    con.execute("UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                (at, conv["id"], user_id))
    return cur.lastrowid


def _turn_payload(kind, conv, message_id, mode, text, *, question=None, options=None,
                  fallback=False, tokens_in=None, tokens_out=None):
    return {
        "type": kind,
        "conversation_id": conv["id"],
        "message_id": message_id,
        "mode": mode,
        "question": question,
        "options": options or [],
        "reply": text,
        "sources": [],
        "fallback": fallback,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def reply_clarify(con, user_id, *, mode, message, ctx, conversation=None) -> dict:
    """澄清回合：不调模型（不扣配额，由 API 层保证），只把反问写进会话。

    路由那一次调用的 token 仍要记账（规格 §9f 第三条：不额外扣次数，但 token 要累加）。
    """
    clarify = ctx.get("clarify") or {}
    route = ctx.get("router") or {}
    tokens_in, tokens_out = _count(route.get("tokens_in")), _count(route.get("tokens_out"))
    conv = conversation or create_conversation(con, user_id, _title(message))
    if clarify.get("exhausted"):
        message_id = _record_turn(con, conv, user_id, message, NOT_FOUND_REPLY,
                                  tokens_in, tokens_out)
        return _turn_payload("not_found", conv, message_id, mode, NOT_FOUND_REPLY,
                             fallback=True, tokens_in=tokens_in, tokens_out=tokens_out)
    options = clarify.get("options") or []
    names = " / ".join(option["name"] for option in options)
    text = f"{CLARIFY_PREFIX}{clarify.get('question') or CLARIFY_QUESTION}"
    if names:
        text += f"：{names}"
    message_id = _record_turn(con, conv, user_id, message, text, tokens_in, tokens_out)
    return _turn_payload("clarify", conv, message_id, mode, text,
                         question=clarify.get("question") or CLARIFY_QUESTION, options=options,
                         tokens_in=tokens_in, tokens_out=tokens_out)



def reply_not_found(con, user_id, *, mode, message, conversation=None) -> dict:
    """点选的概念下没有卡：直说库里没有，不编造（A10 同一条口径）。"""
    conv = conversation or create_conversation(con, user_id, _title(message))
    message_id = _record_turn(con, conv, user_id, message, NOT_FOUND_REPLY)
    return _turn_payload("not_found", conv, message_id, mode, NOT_FOUND_REPLY, fallback=True)


def answer(con, user_id, *, mode, message, ctx, conversation=None) -> dict:
    """跑一次问答并落库（user + assistant 两条消息一次事务，不留半截）。

    token 账 = 路由那一次 + 作答这一次（规格 §9f 第三条）。两次都未知才记 None，不拿 0 顶替。
    """
    conv = conversation or create_conversation(con, user_id, _title(message))
    payload = tutor_prompts.build_messages(ctx, message, history(con, conv["id"]))
    text, tokens_in, tokens_out = _call_llm(payload)
    used_llm = text is not None
    if not used_llm:
        text = library_reply(ctx)
    route = ctx.get("router") or {}
    tokens_in = _add_count(tokens_in, route.get("tokens_in"))
    tokens_out = _add_count(tokens_out, route.get("tokens_out"))
    message_id = _record_turn(con, conv, user_id, message, text, tokens_in, tokens_out)
    return {
        "type": "answer",
        "conversation_id": conv["id"],
        "message_id": message_id,
        "mode": mode,
        "reply": text,
        "sources": sources(ctx),
        "fallback": not used_llm,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _add_count(*values):
    """多次调用的 token 相加；全部未知才返回 None（未知 ≠ 0）。"""
    known = [_count(value) for value in values]
    known = [value for value in known if value is not None]
    return sum(known) if known else None


def _call_llm(payload):
    """返回 (文本, tokens_in, tokens_out)；任何模型侧失败 → (None, None, None) 走库内兜底。"""
    try:
        text, usage = llm.complete(
            payload, feature="tutor",
            timeout=int(_cfg("TUTOR_LLM_TIMEOUT", 60)), with_usage=True)
    except (llm.LLMError, llm.LLMConfigError):
        return None, None, None
    if not text or not str(text).strip():
        return None, None, None
    usage = usage or {}
    return str(text).strip(), _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens"))


def library_reply(ctx) -> str:
    """模型不可用时的库内答复：只复述命中内容，不补任何库外知识。"""
    card = ctx.get("card")
    if card:
        return (f"模型暂时不可用，先给你库里这张卡的原文：\n"
                f"问句：{card['front']}\n答案：{card['back']}")
    hits = ctx.get("hits") or []
    if hits:
        lines = [f"- {hit['concept_name']}：{hit['front']}" for hit in hits[:SOURCES_MAX]]
        return "模型暂时不可用，先列出库里命中的卡片：\n" + "\n".join(lines)
    return "模型暂时不可用，库里也没有检索到相关内容；稍后再试，或换个更具体的说法。"


def sources(ctx) -> list[dict]:
    out, seen = [], set()
    card = ctx.get("card")
    if card:
        out.append({"type": "card", "card_id": card["card_id"], "concept": card["concept_name"],
                    "front": card["front"]})
        seen.add(card["card_id"])
    for hit in ctx.get("hits") or []:
        if hit["card_id"] in seen:
            continue
        seen.add(hit["card_id"])
        out.append({"type": "card", "card_id": hit["card_id"], "concept": hit["concept_name"],
                    "front": hit["front"]})
        if len(out) >= SOURCES_MAX:
            break
    return out

