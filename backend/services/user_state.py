"""按用户隔离的卡片状态（REQ-STATE-01）。

历史问题：`cards.status / learn_count / next_review_at` 是**全组共用**的一列，
导致同组成员互相继承学习进度（Test 能看到 owner 的已学/到期数）。

做法：每个连接上建一张临时表 `_mine`，按当前用户从 `card_reviews` 的
最新一条记录还原该用户的 status/learn_count/next_review_at；
读查询改用 `COALESCE(m.status,'new')`，没有记录即视为未学。
临时表不带参数，改写 SQL 时不改变既有 `?` 绑定顺序。
"""

MINE_DDL = (
    "CREATE TEMP TABLE IF NOT EXISTS _mine("
    "card_id INTEGER PRIMARY KEY, status TEXT, learn_count INTEGER, next_review_at TEXT)"
)

_FILL = (
    # 1) 本人复习记录的最新状态（唯一权威）
    "INSERT INTO _mine(card_id,status,learn_count,next_review_at) "
    "SELECT r.card_id, r.status, r.learn_count, "
    "COALESCE(r.next_review_at, c.next_review_at) FROM card_reviews r "
    "JOIN (SELECT card_id, MAX(id) AS mid FROM card_reviews WHERE user_id=? GROUP BY card_id) t "
    "  ON t.mid=r.id LEFT JOIN cards c ON c.id=r.card_id"
)

# 2) 迁移兜底：本人自己的书上、本人尚无复习记录的卡，沿用旧列状态
#    （旧版把学习状态写在共享的 cards 表；按书的主人归属，不会把别人的进度算给组员）
_LEGACY = (
    "INSERT OR IGNORE INTO _mine(card_id,status,learn_count,next_review_at) "
    "SELECT c.id, c.status, c.learn_count, c.next_review_at FROM cards c "
    "JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id "
    "JOIN books b ON b.id=ch.book_id "
    "WHERE b.owner_id=? AND c.status<>'new'"
)


def ensure_state(con, user_id):
    """保证 `_mine` 存在且是当前用户的视图；幂等，失败不抛（读查询会退化为全 new）。"""
    if not user_id:
        return
    try:
        con.execute(MINE_DDL)
        con.execute("DELETE FROM _mine")
        con.execute(_FILL, (user_id,))
        con.execute(_LEGACY, (user_id,))
    except Exception:  # noqa: BLE001 - 只影响读口径，不阻断请求
        pass
