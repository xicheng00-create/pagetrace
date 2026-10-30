"""Video-specific card reads, isolated behind the card-pool audit boundary."""


def unlocked_card(con, card_id, user_id):
    return con.execute(
        "SELECT c.id,c.concept_id,ch.unlocked_at FROM cards c JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id WHERE c.id=? AND b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) AND ch.unlocked_at IS NOT NULL",
        (card_id, user_id),
    ).fetchone()


def concept_card_ids(con, concept_id):
    return con.execute("SELECT id FROM cards WHERE concept_id=?", (concept_id,)).fetchall()


def linked_cards(con, video_id):
    return con.execute(
        "SELECT c.id,c.front,c.title,l.is_core FROM card_video_links l JOIN cards c ON c.id=l.card_id WHERE l.video_id=? ORDER BY l.is_core DESC,c.id",
        (video_id,),
    ).fetchall()


def render_context(con, card_id):
    return con.execute(
        "SELECT c.id,c.front,c.back,c.title,c.source,c.concept_id,x.name concept_name FROM cards c JOIN concepts x ON x.id=c.concept_id WHERE c.id=?",
        (card_id,),
    ).fetchone()


def neighbours(con, concept_id, card_id):
    return con.execute(
        "SELECT front FROM cards WHERE concept_id=? AND id<>? ORDER BY id LIMIT 6", (concept_id, card_id)
    ).fetchall()


def due_card_ids(con, user_id, limit):
    return con.execute(
        "SELECT c.id FROM cards c JOIN concepts x ON x.id=c.concept_id JOIN chapters ch ON ch.id=x.chapter_id JOIN books b ON b.id=ch.book_id WHERE b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?)) AND ch.unlocked_at IS NOT NULL AND c.next_review_at IS NOT NULL AND c.next_review_at<=datetime('now') ORDER BY c.next_review_at,c.id LIMIT ?",
        (user_id, limit),
    ).fetchall()
