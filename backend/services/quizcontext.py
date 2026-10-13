"""租户隔离的单卡出题上下文。"""
from services import cards as card_pool


def card_context(con, card_id: int, user_id=None):
    """单卡上下文（错题重刷用）：front / back / chapter_id + 出处（书 · 章）。"""
    from services.quizgen import QuizGenError

    if user_id is None:
        from flask import g, has_request_context

        try:
            user_id = getattr(g, "user_id", None)
        except (AttributeError, RuntimeError):
            user_id = 1 if not has_request_context() else None
        if user_id is None:
            raise QuizGenError("authenticated user required")
    row = card_pool.quiz_card_context(con, card_id, user_id).fetchone()
    return dict(row) if row is not None else None
