"""只读父级导航唯一入口；不存在的实体返回 null，且只解析当前租户。"""


def parent_of(con, page, ident, user_id=None):
    if page in ('', 'home'):
        return None
    if page in ('review', 'quiz', 'wrong', 'plan', 'scope', 'subjects'):
        return {'href': '#/', 'label': '首页'}
    queries = {
        'subject': ("SELECT id FROM subjects WHERE id=?", '#/subjects', '知识卡片'),
        'book': ("SELECT s.id, s.name FROM books b JOIN subjects s ON s.id=b.subject_id WHERE b.id=? AND b.owner_id=?", '#/subject/', None),
        'chapter': ("SELECT b.id, b.title AS name FROM chapters ch JOIN books b ON b.id=ch.book_id WHERE ch.id=? AND b.owner_id=?", '#/book/', None),
        'concept': ("SELECT s.id, s.name FROM concepts cp JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id JOIN subjects s ON s.id=b.subject_id WHERE cp.id=? AND b.owner_id=?", '#/subject/', None),
        'card': ("SELECT cp.id, cp.name FROM cards c JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id WHERE c.id=? AND b.owner_id=?", '#/concept/', None),
    }
    if page not in queries or not isinstance(ident, int) or not 0 < ident <= 9223372036854775807:
        return None
    sql, href, label = queries[page]
    params = (ident,) if page == 'subject' else (ident, user_id)
    row = con.execute(sql, params).fetchone()
    if row is None:
        return None
    return {'href': href if label else href + str(row['id']), 'label': label or row['name']}


def response_nav(con, page, ident, user_id=None):
    parent = parent_of(con, page, ident, user_id)
    return {'parent_href': parent['href'] if parent else None,
            'parent_label': parent['label'] if parent else None}
