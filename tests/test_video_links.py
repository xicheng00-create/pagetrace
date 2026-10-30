"""Video relation model assertions."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from api.videos import enqueue  # noqa: E402
from app import create_app  # noqa: E402
from data.db import get_db  # noqa: E402


def test_shared_concept_links(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "links.sqlite3"))
    app = create_app("development")
    with app.app_context():
        con = get_db()
        con.executescript("""
        INSERT INTO users(username,password_hash,created_at) VALUES('u','x',datetime('now'));
        INSERT INTO subjects(name,slug,created_at) VALUES('s','s',datetime('now'));
        INSERT INTO books(subject_id,title,slug,status,created_at,owner_id) VALUES(1,'b','b','active',datetime('now'),1);
        INSERT INTO chapters(book_id,name,anchor,unlocked_at,status) VALUES(1,'c','c',datetime('now'),'active');
        INSERT INTO concepts(concept_uid,chapter_id,name) VALUES('a',1,'a'),('b',1,'b');
        INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,created_at) VALUES(1,1,'1','1','src','1',datetime('now')),(1,1,'2','2','src','2',datetime('now')),(1,1,'3','3','src','3',datetime('now')),(2,1,'4','4','src','4',datetime('now'));
        """)
        from flask import g

        g.user_id = 1
        card = {"id": 1, "concept_id": 1}
        enqueue(con, card)
        rows = con.execute("SELECT card_id,is_core FROM card_video_links").fetchall()
        assert len(rows) == 3 and sum(r["is_core"] for r in rows) == 1
        assert not con.execute(
            "SELECT 1 FROM card_video_links l JOIN cards c ON c.id=l.card_id WHERE c.concept_id=2"
        ).fetchone()
