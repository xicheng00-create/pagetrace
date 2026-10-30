"""NAV：父级由后端提供，查询零写入，缺失实体不猜父级。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import create_app
from data.db import get_db
from services.nav import parent_of, response_nav

from scripts import ingest_kb


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / 'nav.sqlite3'
    monkeypatch.setenv('DATABASE_PATH', str(db))
    con = ingest_kb.connect(str(db))
    ingest_kb.ingest_file(con, Path(__file__).parent / 'fixtures/cards-contract-1.jsonl')
    con.close()
    app = create_app('development')
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_parent_chain_read_only(client):
    with client.application.app_context():
        con = get_db()
        row = con.execute('SELECT c.id card, cp.id concept, ch.id chapter, b.id book, s.id subject, cp.name concept_name, b.title, s.name FROM cards c JOIN concepts cp ON cp.id=c.concept_id JOIN chapters ch ON ch.id=cp.chapter_id JOIN books b ON b.id=ch.book_id JOIN subjects s ON s.id=b.subject_id LIMIT 1').fetchone()
        before = con.total_changes
        con.execute('PRAGMA query_only=ON')
        for page, key, href, label in [
            ('card', 'card', f"#/concept/{row['concept']}", row['concept_name']),
            ('concept', 'concept', f"#/subject/{row['subject']}", row['name']),
            ('chapter', 'chapter', f"#/book/{row['book']}", row['title']),
            ('book', 'book', f"#/subject/{row['subject']}", row['name']),
            ('subject', 'subject', '#/subjects', '知识卡片'),
        ]:
            assert parent_of(con, page, row[key], user_id=1) == {'href': href, 'label': label}
            for ident in (999999, 0, -1, 2**63, None, '1'):
                assert parent_of(con, page, ident) is None
        for page in ('review', 'quiz', 'wrong', 'plan', 'scope', 'subjects'):
            assert parent_of(con, page, None) == {'href': '#/', 'label': '首页'}
        for page in ('home', '', 'unknown'):
            assert parent_of(con, page, None) is None
        assert response_nav(con, 'concept', 999999) == {'parent_href': None, 'parent_label': None}
        assert con.total_changes == before


def test_response_nav_including_locked_missing(client):
    for url, parent in [('/api/books?subject_id=1', '#/subjects'),
                        ('/api/chapters?book_id=1', '#/subject/1'),
                        ('/api/concepts?chapter_id=1', '#/book/1'),
                        ('/api/cards?concept_id=1', '#/subject/1')]:
        data = client.get(url).get_json()['data']
        assert data['nav']['parent_href'] == parent
        assert data['nav']['parent_label']
        missing = client.get(url.rsplit('=', 1)[0] + '=999999')
        if not url.startswith('/api/books'):
            assert missing.status_code == 404
        else:
            assert missing.get_json()['data']['nav'] == {'parent_href': None, 'parent_label': None}
    with client.application.app_context():
        con = get_db()
        con.execute('UPDATE chapters SET unlocked_at=NULL WHERE id=1')
        con.commit()
    data = client.get('/api/concepts?chapter_id=1').get_json()['data']
    assert data['locked'] and data['nav']['parent_href'] == '#/book/1'
