"""POST /api/tutor/chat · GET /api/tutor/quota · GET /api/tutor/conversations/<id>/messages。

第 1 步只要非流式通路（SSE 留到第 3 步）。错误口径：
- 参数不合法 → 400 `E_INVALID_INPUT`；
- 别人的会话 / 不可见的卡 / 不可见的概念 → 404 `E_NOT_FOUND`（不区分「不存在」与「不是你的」，不泄露存在性）；
- 当日次数用尽 → 429 `E_QUOTA` + 「今天的 tutor 次数用完了，明天再来」。
配额在**校验通过后**才扣：404/400 不吃配额。

澄清反问（规格 §9e）：`type=clarify` / `type=not_found` 的回合**不调模型、不扣次数**；
用户点选后带 `concept_id` 重发，命中就在该概念下取卡作答（跳过检索）。
"""
from ai import tutor
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, e_not_found, err, ok
from services import tutor_quota

bp = Blueprint("tutor", __name__)


def _opt_int(payload, key):
    value = payload.get(key)
    if value is None:
        return None
    if type(value) is not int:
        raise ValueError(f"{key} 必须是整数")
    return value


@bp.post("/api/tutor/chat")
def chat():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return e_input("请求体必须是 JSON 对象")
    mode = payload.get("mode") or "free"
    if mode not in tutor.MODES:
        return e_input("mode 只能是 card / free / quiz / plan")
    raw_message = payload.get("message")
    if raw_message is not None and not isinstance(raw_message, str):
        return e_input("message 必须是字符串")
    message = (raw_message or "").strip()
    try:
        conversation_id = _opt_int(payload, "conversation_id")
        card_id = _opt_int(payload, "card_id")
        concept_id = _opt_int(payload, "concept_id")
        subject_id = _opt_int(payload, "subject_id")
        chapter_id = _opt_int(payload, "chapter_id")
    except ValueError as exc:
        return e_input(str(exc))
    if mode == "card" and card_id is None:
        return e_input("mode=card 需要 card_id")
    if not message:
        if mode == "card":
            message = tutor.CARD_DEFAULT_MESSAGE  # 「贴卡讲这张」不需要用户再打字（缺省或空串都算）
        elif concept_id is not None:
            message = tutor.CLARIFY_PICK_MESSAGE  # 点选后重发：允许只带 concept_id
        else:
            return e_input("message 不能为空")
    if len(message) > tutor.MESSAGE_MAX:
        return e_input(f"message 超过 {tutor.MESSAGE_MAX} 字")

    con, user_id = get_db(), g.user_id
    try:
        conversation = tutor.load_conversation(con, user_id, conversation_id) if conversation_id else None
        ctx = tutor.build(con, user_id, mode=mode, message=message, card_id=card_id,
                          subject_id=subject_id, chapter_id=chapter_id, concept_id=concept_id,
                          conversation=conversation)
    except tutor.ConversationNotFound:
        return e_not_found("会话不存在")
    except tutor.CardNotFound:
        return e_not_found("卡片不存在")
    except tutor.ConceptNotFound:
        return e_not_found("概念不存在")

    # 澄清反问 / 库内无页：不调模型、不扣次数（规格 §9e）
    if ctx.get("clarify"):
        result = tutor.reply_clarify(con, user_id, mode=mode, message=message, ctx=ctx,
                                     conversation=conversation)
        con.commit()
        result["quota"] = tutor_quota.state(con, user_id)
        return ok(result)
    if concept_id is not None and not ctx.get("hits"):
        result = tutor.reply_not_found(con, user_id, mode=mode, message=message,
                                       conversation=conversation)
        con.commit()
        result["quota"] = tutor_quota.state(con, user_id)
        return ok(result)

    try:
        quota = tutor_quota.consume(con, user_id)
    except tutor_quota.TutorQuotaError as exc:
        return err("E_QUOTA", str(exc), 429)

    result = tutor.answer(con, user_id, mode=mode, message=message, ctx=ctx,
                          conversation=conversation)
    tutor_quota.add_tokens(con, user_id, result["tokens_in"], result["tokens_out"])
    con.commit()
    result["quota"] = quota
    return ok(result)


@bp.get("/api/tutor/quota")
def quota():
    return ok(tutor_quota.state(get_db(), g.user_id))


@bp.get("/api/tutor/conversations/<int:conversation_id>/messages")
def conversation_messages(conversation_id):
    con = get_db()
    try:
        conversation = tutor.load_conversation(con, g.user_id, conversation_id)
    except tutor.ConversationNotFound:
        return e_not_found("会话不存在")
    return ok({"conversation_id": conversation["id"], "title": conversation["title"],
               "messages": tutor.messages(con, conversation["id"])})
