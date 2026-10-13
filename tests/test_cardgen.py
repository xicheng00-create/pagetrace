import hashlib
import json
from pathlib import Path

import pytest
from test_upload import client, pdf_bytes, submit  # noqa: F401

from data.db import get_db
from services import cardgen, llm
from services.upload import extract_text, save_drafts
from services.segment import segment_book


def row():
    return json.loads((Path(__file__).parent / 'fixtures/cards-contract-1.jsonl').read_text().splitlines()[0])


def block():
    return {'text': '原文', 'text_sha256': hashlib.sha256('原文'.encode()).hexdigest(),
            'book_hash': 'hash', 'chapter': '第1章'}


def test_no_llm_call_on_rerun(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, 'complete_block', lambda *a, **k: calls.append(k) or json.dumps([row()]))
    first = cardgen.generate_block(block(), tmp_path)
    assert cardgen.generate_block(block(), tmp_path) == first
    assert len(calls) == 1
    next((tmp_path / 'books/hash/cards').glob('*.json')).unlink()
    cardgen.generate_block(block(), tmp_path)
    assert len(calls) == 2
    assert calls[0]['thinking_disabled'] is True


def test_payload_thinking_disabled(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    bodies = []
    def post(url, **kwargs):
        bodies.append(kwargs['json'])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'choices': [{'message': {'content': json.dumps([row()])}}]})
    monkeypatch.setitem(sys.modules, 'requests', SimpleNamespace(post=post))
    cardgen.generate_block(block(), tmp_path)
    assert bodies[0]['extra_body']['thinking'] == {'type': 'disabled'}
    assert 'thinking' not in bodies[0]
    assert 'thinking_disabled=True' in Path(cardgen.__file__).read_text()


def test_cards_pass_existing_gate(client):
    job_id = submit(client, pdf_bytes()).json['data']['id']
    r = row()
    with client.application.app_context():
        con = get_db()
        assert save_drafts(con, job_id, cardgen.gate([r, r])) == 1
        assert con.execute('SELECT COUNT(*) FROM cards').fetchone()[0] == 0
        malformed = {**r}
        del malformed['title']
        for bad in (malformed, {**r, 'answer_points': ['甲'*223]}):
            with pytest.raises(ValueError):
                save_drafts(con, job_id, [bad])
            assert con.execute('SELECT COUNT(*) FROM card_drafts').fetchone()[0] == 1
        f = json.loads((Path(__file__).parent / 'fixtures/cardlen/合成示例书3.json').read_text())
        long = {**json.loads(f['input']), 'subcards': f['names']}
        assert save_drafts(con, job_id, cardgen.gate([long])) == len(f['expected'])


def test_real_pdf_blocks_mock_model(client, monkeypatch):
    metadata = submit(client, pdf_bytes()).json['data']
    root = Path(client.application.config['UPLOAD_ROOT'])
    extracted = extract_text(root / 'in' / (metadata['book_hash']+'.pdf'), root)
    blocks = segment_book(extracted['path'], metadata['book_hash'])['blocks']
    monkeypatch.setattr(llm, 'complete_block', lambda *a, **k: json.dumps([row()]))
    rows = [r for b in blocks for r in cardgen.generate_block(b, root)]
    with client.application.app_context():
        assert save_drafts(get_db(), metadata['id'], rows) >= 1


def test_invalid_outputs(tmp_path, monkeypatch):
    from services.cardgen import CardGateError, CardParseError
    with pytest.raises(ValueError):
        cardgen.generate_block({**block(), 'text_sha256': 'bad'}, tmp_path)
    for raw, exception in (('{}', CardParseError), ('[{}]', CardGateError), ('not json', CardParseError)):
        monkeypatch.setattr(llm, 'complete_block', lambda *a, _raw=raw, **k: _raw)
        with pytest.raises(exception):
            cardgen.generate_block(block(), tmp_path)
    for bad in ({**row(), 'chapter': 1}, {**row(), 'answer_points': [3]}):
        with pytest.raises(ValueError):
            cardgen.gate([bad])
    with pytest.raises(ValueError):
        cardgen.gate([{}])


def test_pool_reuse_no_llm(client, monkeypatch):
    from services import llm
    data = pdf_bytes()
    metadata = submit(client, data).json['data']
    with client.application.app_context():
        con = get_db()
        from scripts.ingest_kb import ingest_file
        ingest_file(con, Path(__file__).parent / 'fixtures/cards-contract-1.jsonl')
        con.execute('UPDATE books SET book_hash=?', (metadata['book_hash'],))
        con.commit()
    monkeypatch.setattr(llm, 'complete_block', lambda *a, **k: pytest.fail('不应调用模型'))
    response = submit(client, data).json['data']
    assert response['reused'] is True
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM books').fetchone()[0] == 1
        assert get_db().execute('SELECT COUNT(*) FROM upload_jobs').fetchone()[0] == 1


def test_explicit_confirmation_only(client):
    job_id = submit(client, pdf_bytes()).json['data']['id']
    with client.application.app_context():
        con = get_db()
        save_drafts(con, job_id, [row()])
        con.execute("UPDATE upload_jobs SET status='ready' WHERE id=?", (job_id,))
        con.commit()
        assert con.execute('SELECT COUNT(*) FROM cards').fetchone()[0] == 0
    state = client.get('/api/drafts').json['data']
    assert state['can_confirm']
    draft_id = state['drafts'][0]['id']
    assert client.put(f'/api/drafts/{draft_id}', json={'status': 'deleted'}).json['code'] == 0
    assert client.post('/api/drafts/confirm').status_code == 400
    assert client.put(f'/api/drafts/{draft_id}', json={'status': 'kept'}).json['code'] == 0
    assert client.put(f'/api/drafts/{draft_id}', json={'status': 'bad'}).status_code == 400
    assert client.post('/api/drafts/confirm').json['data']['confirmed'] == 1
    assert client.post('/api/drafts/confirm').status_code == 400
    assert client.put(f'/api/drafts/{draft_id}', json={'status': 'kept'}).status_code == 404
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM cards').fetchone()[0] == 1


def test_upload_book_identity_isolated(client):
    from scripts.ingest_kb import ingest_file
    from services.upload import confirm_drafts, find_pooled_book
    with client.application.app_context():
        con = get_db()
        ingest_file(con, Path(__file__).parent / 'fixtures/cards-contract-1.jsonl')
        original = dict(con.execute('SELECT * FROM books').fetchone())
        for book_hash in ('A', 'B'):
            job = con.execute("INSERT INTO upload_jobs(owner_id,book_hash,filename,pages,status,stage,created_at,updated_at) VALUES(1,?,'book.pdf',1,'ready','ready','now','now')", (book_hash,)).lastrowid
            save_drafts(con, job, [row()])
            confirm_drafts(con)
            assert dict(con.execute('SELECT * FROM books WHERE id=?', (original['id'],)).fetchone()) == original
            assert find_pooled_book(con, 'A')
        books = con.execute('SELECT source,book_hash FROM books ORDER BY id').fetchall()
        assert len(books) == 3
        assert [r['source'] for r in books] == ['kb', 'upload', 'upload']
        assert [r['book_hash'] for r in books] == [None, 'A', 'B']


def test_final_split_rows_never_regated(client, tmp_path, monkeypatch):
    r = {**row(), 'answer_points': ['甲。'*100, '甲。'*100],
         'subcards': [{'name': '相同', 'question': '相同问句？'}]*2}
    calls = []
    monkeypatch.setattr(llm, 'complete_block', lambda *a, **k: calls.append(1) or json.dumps([r]))
    first = cardgen.generate_block(block(), tmp_path)
    assert len(first) == 2
    assert cardgen.gate(first) == first
    monkeypatch.setattr(cardgen, 'gate', lambda *a: pytest.fail('最终产物不得再闸门'))
    assert cardgen.generate_block(block(), tmp_path) == first
    assert len(calls) == 1
    job_id = submit(client, pdf_bytes()).json['data']['id']
    with client.application.app_context():
        con = get_db()
        assert save_drafts(con, job_id, first) == 2
        saved = [json.loads(r[0]) for r in con.execute('SELECT payload FROM card_drafts ORDER BY id')]
        assert saved == first
