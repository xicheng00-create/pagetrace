"""只读父级导航唯一入口；不存在的实体返回 null，且只解析当前租户。"""

VISIBLE_BOOK_SQL = (
    "b.owner_id IN (SELECT u2.id FROM users u2 "
    "WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))"
)


def parent_of(con, page, ident, user_id=None):
    if page in ('', 'home'):
        return None
    if page in ('review', 'quiz', 'wrong', 'plan', 'scope', 'subjects'):
        return {'href': '#/', 'label': '首页'}
    visibility, visibility_params = VISIBLE_BOOK_SQL, [user_id]
    queries = {
        'subject': ("SELECT id FROM subjects WHERE id=?", '#/subjects', '知识卡片'),
        'book': (f"SELECT s.id, s.name FROM books b JOIN subjects s ON s.id=b.subject_id WHERE b.id=? AND {visibility}", '#/subject/', None),
        'chapter': (f"SELECT b.id, b.title AS name FROM chapters ch JOIN books b ON b.id=ch.book_id WHERE ch.id=? AND {visibility}", '#/book/', None),
        'concept': (f"SELECT s.id, s.name FROM concepts cp JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id JOIN subjects s ON s.id=b.subject_id WHERE cp.id=? AND {visibility}", '#/subject/', None),
        'card': (f"SELECT cp.id, cp.name FROM cards c JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id WHERE c.id=? AND {visibility}", '#/concept/', None),
    }
    if page not in queries or not isinstance(ident, int) or not 0 < ident <= 9223372036854775807:
        return None
    sql, href, label = queries[page]
    params = (ident,) if page == 'subject' else (ident, *visibility_params)
    row = con.execute(sql, params).fetchone()
    if row is None:
        return None
    return {'href': href if label else href + str(row['id']), 'label': label or row['name']}


def response_nav(con, page, ident, user_id=None):
    parent = parent_of(con, page, ident, user_id)
    return {'parent_href': parent['href'] if parent else None,
            'parent_label': parent['label'] if parent else None}
