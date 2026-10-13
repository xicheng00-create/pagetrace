"""出题·测验 API（QUIZ-001…006）+ 错题本（WRONG-001）。

- POST /api/quiz/session         {"subject?","size?"} → {session_id,size,items:[{id,type,stem,options}]}
                                 （**响应绝不含 `answer_key`**，QUIZ-001）
- POST /api/quiz/answer          {"session_id","item_id","my_answer"} → 判分 + 追加 quiz_attempts
                                 → {is_correct, correct_answer, progress}
- GET  /api/quiz/session/<sid>           → 进行中进度 {total,answered,correct,score,current_item_id}
- GET  /api/quiz/session/<sid>/result    → {answered,correct,score,wrong:[{stem,correct_answer,my_answer}]}
- GET  /api/quiz/session/<sid>/answer/<card_id>  → 旧端点保留可用（「看答案」），避免线上 500
- GET  /api/wrong                        → 按卡聚合、按错次降序
- POST /api/wrong/retry                  → {"card_id"} 对该卡发起单题测验
"""
from data.db import get_db
from flask import Blueprint, request
from middleware.errors import e_input, e_not_found, ok
from services import quiz, scope, streak

bp = Blueprint("quiz", __name__)


@bp.post("/api/quiz/session")
def start():
    body = request.get_json(silent=True) or {}
    con = get_db()
    sid = None
    if body.get("subject"):
        row = con.execute("SELECT id FROM subjects WHERE slug=? OR name=?",
                          (body["subject"], body["subject"])).fetchone()
        if row is None:
            return e_not_found("学科不存在")
        sid = row["id"]
    try:
        data = quiz.start_session(con, subject_id=sid, size=body.get("size"),
                                  book_ids=scope.get_book_scope(con))
    except quiz.QuizError as exc:
        return e_input(str(exc))
    return ok(data)


@bp.post("/api/quiz/answer")
def submit():
    body = request.get_json(silent=True) or {}
    for field in ("session_id", "item_id", "my_answer"):
        if body.get(field) in (None, ""):
            return e_input(f"缺少 {field}")
    try:
        item_id = int(body["item_id"])
    except (TypeError, ValueError):
        return e_input("item_id 必须为整数")
    try:
        data = quiz.answer(get_db(), str(body["session_id"]), item_id, str(body["my_answer"]))
    except quiz.QuizResourceNotFound as exc:
        return e_not_found(str(exc))
    except quiz.QuizError as exc:
        return e_input(str(exc))
    streak.record_day(get_db())
    return ok(data)


@bp.get("/api/quiz/session/<session_id>")
def status(session_id: str):
    try:
        return ok(quiz.progress(session_id))
    except quiz.QuizError as exc:
        return e_not_found(str(exc))


@bp.get("/api/quiz/session/<session_id>/result")
def session_result(session_id: str):
    try:
        return ok(quiz.result(get_db(), session_id))
    except quiz.QuizError as exc:
        return e_not_found(str(exc))


@bp.get("/api/quiz/session/<session_id>/answer/<int:card_id>")
def reveal(session_id: str, card_id: int):
    try:
        return ok(quiz.reveal(get_db(), session_id, card_id))
    except quiz.QuizError as exc:
        return e_not_found(str(exc))


@bp.get("/api/wrong")
def wrong():
    return ok({"items": quiz.wrong_list(get_db())})


@bp.post("/api/wrong/retry")
def wrong_retry():
    body = request.get_json(silent=True) or {}
    if body.get("card_id") in (None, ""):
        return e_input("缺少 card_id")
    try:
        card_id = int(body["card_id"])
    except (TypeError, ValueError):
        return e_input("card_id 必须为整数")
    try:
        data = quiz.retry_session(get_db(), card_id)
    except quiz.QuizError as exc:
        return e_not_found(str(exc))
    return ok(data)
