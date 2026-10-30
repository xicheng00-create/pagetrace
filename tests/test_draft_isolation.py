from pathlib import Path

from data.db import get_db
from scripts.ingest_kb import ingest_file
from services import clock
from test_upload import client, pdf_bytes, submit  # noqa: F401


def test_draft_invisible_to_all_read_apis(client):
    with client.application.app_context():
        con = get_db()
        ingest_file(con, Path(__file__).parent / 'fixtures/cards-contract-1.jsonl')
        card = con.execute('SELECT id FROM cards ORDER BY id LIMIT 1').fetchone()[0]
        con.execute("INSERT INTO card_reviews(user_id,card_id,learned_at,result) VALUES(1,?,?,'good')",
                    (card, clock.now_iso()))
        con.commit()
        initial = con.execute('SELECT COUNT(*) FROM cards').fetchone()[0]
        assert initial >= 1
        assert con.execute('SELECT COUNT(*) FROM card_reviews').fetchone()[0] >= 1
    job_id = submit(client, pdf_bytes()).json['data']['id']
    paths = ['/api/today', '/api/plan', '/api/task', '/api/report', '/api/weak',
             '/api/progress', '/api/subjects', '/api/streak', '/api/cards?concept_id=1',
             '/api/review/1', '/api/wrong', '/api/quiz/session/nonexistent',
             '/api/quiz/session/nonexistent/result', '/api/quiz/session/nonexistent/answer/1']
    before = {path: client.get(path).json for path in paths}
    assert all(value['code'] == 0 for path, value in before.items()
               if path not in {'/api/quiz/session/nonexistent',
                               '/api/quiz/session/nonexistent/result',
                               '/api/quiz/session/nonexistent/answer/1', '/api/review/1'})
    assert before['/api/cards?concept_id=1']['data']['cards']
    secret = 'DRAFT-SECRET-ISOLATION-CANARY'
    with client.application.app_context():
        con = get_db()
        con.execute("INSERT INTO card_drafts(job_id,book_hash,payload,confidence,created_at) "
                    "VALUES(?,'hash',?,'low',?)", (job_id, '{\"answer_points\":[\"' + secret + '\"]}', clock.now_iso()))
        con.commit()
        assert con.execute('SELECT COUNT(*) FROM cards').fetchone()[0] == initial
    with client.application.app_context():
        before_response = {path: client.get(path).get_data(as_text=True) for path in paths}
    assert {path: client.get(path).json for path in paths} == before
    assert all(secret not in body for body in before_response.values())


def test_no_draft_read_bypass():
    root = Path(__file__).resolve().parents[1] / 'backend'
    allowed = {'services/upload.py', 'services/jobs.py', 'data/models.py'}
    for folder in ('api', 'services'):
        for path in (root / folder).rglob('*.py'):
            if path.relative_to(root).as_posix() not in allowed:
                assert 'card_drafts' not in path.read_text(), path
