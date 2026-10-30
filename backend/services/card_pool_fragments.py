"""卡池 SQL 片段常量（非查询执行；从 cards.py 拆出以满足单文件 <300 行）。"""

_COLS = (
    "c.id AS card_id, c.front, c.back, COALESCE(m.status,'new') AS status, COALESCE(m.learn_count,0) AS learn_count, m.next_review_at AS next_review_at, c.source,"
    " c.title,"
    " cp.id AS concept_id, cp.name AS concept,"
    " ch.id AS chapter_id, ch.name AS chapter, ch.order_no AS chapter_order,"
    " b.title AS book, s.name AS subject, s.id AS subject_id"
)
_FROM = (
    " FROM cards c LEFT JOIN _mine m ON m.card_id=c.id"
    " JOIN concepts cp ON cp.id = c.concept_id"
    " JOIN chapters ch ON ch.id = cp.chapter_id"
    " JOIN books b ON b.id = ch.book_id"
    " JOIN subjects s ON s.id = c.subject_id"
    " WHERE ch.unlocked_at IS NOT NULL"
)
_DUE_TAIL = (
    " AND COALESCE(m.status,'new') <> 'new' AND m.next_review_at IS NOT NULL AND m.next_review_at <= ?"
    " ORDER BY m.next_review_at ASC, c.id ASC LIMIT ?"
)
_NEW_TAIL = " AND COALESCE(m.status,'new') = 'new' ORDER BY ch.order_no ASC, cp.id ASC, c.id ASC LIMIT ?"

_PRIORITY = (
    "CASE WHEN (SELECT r.result FROM card_reviews r WHERE r.card_id=c.id"
    " AND r.user_id=? AND substr(r.learned_at,1,10)=? ORDER BY r.learned_at DESC, r.id DESC LIMIT 1)='again'"
    " THEN 0 ELSE 1 END"
)
_DUE_ORDER = " ORDER BY m.next_review_at ASC, c.id ASC LIMIT ?"
