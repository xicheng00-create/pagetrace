from pathlib import Path
from test_upload import client, pdf_bytes, submit  # noqa: F401

from data.db import get_db


def test_quota_blocks_over_limit(client):
    client.application.config['UPLOAD_MONTHLY_PAGES'] = 2
    assert submit(client, pdf_bytes()).status_code == 202
    files = list(Path(client.application.config['UPLOAD_ROOT']).rglob('*.pdf'))
    response = submit(client, pdf_bytes())
    assert response.status_code == 429
    assert response.json['code'] == 'E_QUOTA' and '2 页' in response.json['msg']
    assert list(Path(client.application.config['UPLOAD_ROOT']).rglob('*.pdf')) == files
    with client.application.app_context():
        assert get_db().execute('SELECT COUNT(*) FROM upload_jobs').fetchone()[0] == 1
    assert client.get('/api/upload/quota').json['data']['remaining'] == 0
    assert not client.get('/api/drafts').json['data']['can_confirm']


def test_upload_availability_from_backend(client):
    state = client.get('/api/upload/quota').json['data']
    assert not state['can_upload'] and state['reason']
    client.application.config['UPLOAD_WORKER_ENABLED'] = True
    state = client.get('/api/upload/quota').json['data']
    assert state['can_upload'] and state['reason'] == ''
    client.application.config['UPLOAD_MONTHLY_PAGES'] = 0
    state = client.get('/api/upload/quota').json['data']
    assert not state['can_upload'] and '额度' in state['reason']
