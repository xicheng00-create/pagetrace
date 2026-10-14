"""测验会话（QUIZ-001…006）+ 错题本（WRONG-001）。

- 出题：`services/quizgen`（缓存优先 → LLM → 机械降级；QUIZ-002/003）。
- 判分：**确定性** —— 本题内 `grade()` 单一入口，`my_answer == answer_key` → 满分、否则 0。
  本模块**不得引入任何网络/LLM 客户端**（QUIZ-004 反向断言：判分路径零网络、零 LLM）。
- 作答落库 `quiz_attempts`（**追加不覆盖**，UTC ISO 8601；QUIZ-006），并**复用
  `review_sched.apply_result`**（唯一一套调度，不另写）。
- 得分口径（QUIZ-005）：`y = 已作答题数`（未答不入分母）、`x = 判对题数`、
  `z = round(x / y * 100)`，`y = 0 → z = 0`。

会话存内存（重启失效可接受）；得分/错题全部从库内 `quiz_attempts` 重算，故重启后结果仍可读。
"""

from __future__ import annotations

import uuid

from config import BaseConfig
from flask import g

from services import cards as card_pool
from services import labels, quizgen, quiztext, review_sched, unlock

# session_id -> {"items": {item_id: item}}
_SESSIONS: dict[str, dict] = {}


def _uid():
    try:
        uid = getattr(g, "user_id", None)
    except RuntimeError:
        uid = None
    if uid is None:
        try:
            from flask import has_request_context
            if not has_request_context():
                return 1
        except RuntimeError:
            return 1
        raise RuntimeError("authenticated user required")
    return uid


# 判对 → good / 判错 → again（自评三档语义复用；QUIZ-006/REVIEW-001 唯一调度）
_RESULT_MAP = {True: "good", False: "again"}


class QuizError(Exception):
    """会话/参数错误；由 API 层翻译成 4xx。"""


class QuizResourceNotFound(QuizError):
    """Missing or foreign session; expose the same response for both."""


def grade(my_answer, answer_key) -> bool:
    """确定性判分（QUIZ-004）：完全匹配（区分大小写、不做 trim/模糊）→ True，否则 False。"""
    return str(my_answer) == str(answer_key)


def score_pct(correct, answered) -> int:
    """得分 / 正确率**单点入口**（QUIZ-005）：`round(correct / answered * 100)`；分母 0 → 0。

    会话进度、结果页（QUIZ-005）与本周概况（RPT-001）**共用本函数**，
    分子分母口径（分母 = 已作答题数，未答不入）只在这一点定义，杜绝漂移。
    """
    answered = int(answered or 0)
    return round(int(correct or 0) / answered * 100) if answered else 0


def public_item(item: dict, card: dict | None = None, *, ctx: str) -> dict:
    """会话可见字段：**绝不含 `answer_key`**（QUIZ-001 反向断言）。

    `book` / `chapter` 只是微标签出处（DESIGN.md §3），不泄漏答案。
    `ctx` = 会话 id：选项呈现顺序按 `(ctx, item_id)` 确定性置换（QUIZ-014），
    同一会话内恒定、跨会话重排；答案位置不固定。
    """
    out = {
        "id": item["id"],
        "card_id": item["card_id"],
        "type": item["type"],
        "stem": item["stem"],
        "options": quiztext.display_options(item["options"], ctx=ctx, item_id=item["id"]),
    }
    if card:
        out["book"] = card.get("book")
        out["chapter"] = card.get("chapter")
        out["source_label"] = labels.display_fields(card)["source_label"]
    return out


def _quiz_pool(con, subject_id=None, book_ids=None, user_id=None):
    user_id = user_id or _uid()
    """已解锁章内已学卡池：错答优先、到期其次，其余稳定轮转。SCOPE 按书过滤。"""
    rows = card_pool.learned_quiz_cards(con, subject_id, book_ids, user_id).fetchall()
    data = [dict(row) for row in rows]
    for card in data:
        card["wrong_count"] = con.execute(
            "SELECT COUNT(*) FROM quiz_attempts WHERE card_id=? AND user_id=? AND is_correct=0",
            (card["card_id"], user_id),
        ).fetchone()[0]
        card["last_answer"] = (
            con.execute(
                "SELECT MAX(created_at) FROM quiz_attempts WHERE card_id=? AND user_id=?",
                (card["card_id"], user_id),
            ).fetchone()[0]
            or ""
        )
    return sorted(
        data,
        key=lambda c: (
            -c["wrong_count"],
            c["next_review_at"] is None,
            c["next_review_at"] or "",
            c["last_answer"],
            c["card_id"],
        ),
    )


def start_session(con, *, subject_id=None, size=None, book_ids=None) -> dict:
    size = int(size if size is not None else BaseConfig.QUIZ_TASK_TARGET)
    if size <= 0:
        raise QuizError("size 必须为正整数")
    size = min(size, BaseConfig.QUIZ_MAX_SIZE)
    uid = _uid()
    cards = _quiz_pool(con, subject_id, book_ids, uid)[:size]
    # 同一张卡只允许进入一次会话，即使底层池返回重复项。
    cards = list({card["card_id"]: card for card in reversed(cards)}.values())
    items = quizgen.ensure_items(con, cards, uid) if cards else []
    meta = {c["card_id"]: c for c in cards}
    sid = uuid.uuid4().hex
    _SESSIONS[sid] = {"user_id": uid, "items": {it["id"]: it for it in items}, "answers": {}}
    return {
        "session_id": sid,
        "size": len(items),
        "items": [public_item(it, meta.get(it["card_id"]), ctx=sid) for it in items],
    }


def retry_session(con, card_id: int) -> dict:
    """错题重刷（WRONG-001）：对指定卡发起一次单题测验，作答追加到 quiz_attempts。"""
    ctx = quizgen.card_context(con, card_id, _uid())
    if ctx is None:
        raise QuizError("卡不存在")
    sid = uuid.uuid4().hex
    items = quizgen.ensure_items(con, [ctx], _uid())
    _SESSIONS[sid] = {"user_id": _uid(), "items": {it["id"]: it for it in items}, "answers": {}}
    return {"session_id": sid, "size": len(items),
            "items": [public_item(it, ctx, ctx=sid) for it in items]}


def _session(session_id: str) -> dict:
    s = _SESSIONS.get(session_id)
    if s is None or s.get("user_id") != _uid():
        raise QuizResourceNotFound("会话不存在或已失效")
    return s


def answer(con, session_id: str, item_id: int, my_answer: str) -> dict:
    """判分 + 追加 quiz_attempts + 复用 review_sched 推进调度。"""
    s = _session(session_id)
    item = s["items"].get(int(item_id))
    if item is None:
        raise QuizError("该题不属于本会话")
    my = str(my_answer)
    if not my.strip():
        raise QuizError("答案不能为空")
    correct = grade(my, item["answer_key"])
    con.execute(
        "INSERT INTO quiz_attempts(item_id,card_id,session_id,my_answer,is_correct,created_at,user_id)"
        " VALUES(?,?,?,?,?,?,?)",
        (item["id"], item["card_id"], session_id, my, 1 if correct else 0, _utc_iso(), _uid()),
    )
    state = review_sched.apply_result(con, item["card_id"], _RESULT_MAP[correct])
    unlocked = unlock.maybe_unlock(con)
    con.commit()
    s["answers"][item["id"]] = correct
    return {
        "is_correct": correct,
        "correct_answer": item["answer_key"],
        "card": state,
        "unlocked": unlocked,
        "progress": progress(session_id),
    }


def progress(session_id: str) -> dict:
    """会话轻量进度（内存态）：供测验进行中展示；得分口径同结果页（QUIZ-005）。"""
    s = _session(session_id)
    answered = dict(s["answers"])
    correct = sum(1 for v in answered.values() if v)
    return {
        "total": len(s["items"]),
        "answered": len(answered),
        "correct": correct,
        "score": score_pct(correct, len(answered)),
        "current_item_id": next((iid for iid in s["items"] if iid not in answered), None),
    }


def result(con, session_id: str) -> dict:
    """结束页（QUIZ-005/006）：从 quiz_attempts 重算 x/y/z 与错题明细。"""
    s = _SESSIONS.get(session_id)
    if s is not None and s.get("user_id") != _uid():
        raise QuizResourceNotFound("会话不存在或已失效")
    rows = con.execute(
        "SELECT id, item_id, my_answer, is_correct FROM quiz_attempts"
        " WHERE session_id=? AND user_id=? ORDER BY id",
        (session_id, _uid()),
    ).fetchall()
    if s is None and not rows:
        raise QuizResourceNotFound("会话不存在或已失效")
    latest: dict[int, object] = {}
    for r in rows:  # 同一题多次作答以最后一次为准
        latest[r["item_id"]] = r
    answered = len(latest)
    correct = sum(1 for r in latest.values() if r["is_correct"])
    score = score_pct(correct, answered)
    wrong = []
    items = []
    for item_id, r in latest.items():
        it = con.execute(
            "SELECT card_id, type, stem, options, answer_key FROM quiz_items WHERE id=?", (item_id,)
        ).fetchone()
        parsed_options = __import__("json").loads(it["options"])
        context = quizgen.card_context(con, it["card_id"], _uid())
        display = labels.display_fields(context or {})
        items.append(
            {
                **display,
                "item_id": item_id,
                "card_id": it["card_id"],
                "type": it["type"],
                "stem": it["stem"],
                # 呈现顺序必须与作答时一致（QUIZ-014）：同一 ctx=session_id 置换相同。
                "options": quiztext.display_options(parsed_options, ctx=session_id, item_id=item_id),
                "my_answer": r["my_answer"],
                "correct_answer": it["answer_key"],
                "is_correct": bool(r["is_correct"]),
            }
        )
        if not r["is_correct"]:
            wrong.append(
                {"stem": it["stem"], "correct_answer": it["answer_key"], "my_answer": r["my_answer"]}
            )
    return {"answered": answered, "correct": correct, "score": score, "wrong": wrong, "items": items}


def reveal(con, session_id: str, card_id: int) -> dict:
    """旧端点保留（避免线上 500）：仅在显式请求时返回该卡答案要点。不判分、不比对。"""
    s = _session(session_id)
    if card_id not in {it["card_id"] for it in s["items"].values()}:
        raise QuizError("该题不属于本会话")
    row = card_pool.card_answer(con, card_id, _uid()).fetchone()
    if row is None:
        raise QuizError("卡不存在")
    points = labels.display_fields(dict(row))["answer_points"]
    return {"card_id": card_id, "question": row["front"], "answer_points": points}


# —— 错题本（WRONG-001） ——
def wrong_list(con, user_id=None) -> list[dict]:
    user_id = user_id or _uid()
    """按**卡**聚合、**按错次降序**；每条含正确答案 / 我的答案（可展开对照）+ `status_label`（MAST-003）。"""
    rows = card_pool.wrong_answer_cards(con, user_id).fetchall()
    return [
        {
            **dict(r),
            **labels.display_fields({**dict(r), **(quizgen.card_context(con, r["card_id"], user_id) or {})}),
            "status_label": labels.status_label(r["status"]),
        }
        for r in rows
    ]


def _utc_iso() -> str:
    """作答时间戳：**UTC ISO 8601**（QUIZ-006）。"""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")
