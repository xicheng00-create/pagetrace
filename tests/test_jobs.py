import pytest
from data.db import get_db
from services.jobs import get_job, transition
from test_upload import client, pdf_bytes, submit  # noqa: F401


def test_illegal_transition_rejected(client):
    job_id = submit(client, pdf_bytes()).json['data']['id']
    with client.application.app_context():
        con = get_db()
        with pytest.raises(ValueError, match='非法'):
            transition(con, job_id, 'ready', 100, user_id=1)
        with pytest.raises(ValueError, match='非法'):
            transition(con, 999, 'extracting', 1, user_id=1)
        with pytest.raises(ValueError, match='进度'):
            transition(con, job_id, 'extracting', -1, user_id=1)
        for stage, progress in [('extracting', 10), ('segmenting', 20), ('cardgen', 30),
                                ('gated', 90), ('ready', 100)]:
            transition(con, job_id, stage, progress, user_id=1)
    assert client.get(f'/api/upload/jobs/{job_id}').json['data']['progress'] == 100
    assert client.get('/api/upload/jobs/999').status_code == 404


def test_failure_retry_transition(client):
    job_id = submit(client, pdf_bytes()).json['data']['id']
    with client.application.app_context():
        con = get_db()
        transition(con, job_id, 'failed', 0, '等待规范', user_id=1)
        transition(con, job_id, 'queued', 0, user_id=1)
    assert client.get(f'/api/upload/jobs/{job_id}').json['data']['stage'] == 'queued'


def test_job_resume_after_restart(client, monkeypatch):
    import json
    from pathlib import Path

    from services import llm
    from services.worker import run_job
    fixture = Path(__file__).parent / 'fixtures/cards-contract-1.jsonl'
    calls = []
    monkeypatch.setattr(llm, 'complete_block', lambda *a, **k:
                        calls.append(1) or json.dumps([json.loads(fixture.read_text().splitlines()[0])]))
    job_id = submit(client, pdf_bytes()).json['data']['id']
    root = client.application.config['UPLOAD_ROOT']
    with client.application.app_context():
        con = get_db()
        for stage, progress in [('extracting', 10), ('segmenting', 20), ('cardgen', 30)]:
            transition(con, job_id, stage, progress, user_id=1)
        run_job(con, job_id, root, user_id=1)
        assert con.execute('SELECT status FROM upload_jobs WHERE id=?', (job_id,)).fetchone()[0] == 'ready'
        first = len(calls)
        drafts = [tuple(r) for r in con.execute("SELECT * FROM card_drafts ORDER BY id")]
        con.execute("UPDATE upload_jobs SET status='cardgen',stage='cardgen' WHERE id=?", (job_id,))
        con.commit()
        run_job(con, job_id, root, user_id=1)
        assert len(calls) == first
        assert [tuple(r) for r in con.execute("SELECT * FROM card_drafts ORDER BY id")] == drafts
        assert drafts
        assert con.execute('SELECT COUNT(*) FROM cards').fetchone()[0] == 0
        run_job(con, 999, root, user_id=1)
        run_job(con, job_id, root, user_id=1)


def test_worker_failure_and_drain(client, monkeypatch):
    from services import llm
    from services.worker import drain, start
    monkeypatch.setattr(llm, 'complete_block', lambda *a, **k: 'bad json')
    job_id = submit(client, pdf_bytes()).json['data']['id']
    drain(client.application)
    assert client.get(f'/api/upload/jobs/{job_id}').json['data']['status'] == 'failed'
    start(client.application)


def test_single_concurrency(client, monkeypatch, caplog):
    """Two drain callers: second job stays queued while first provider is held."""
    import json
    import logging
    import threading
    from pathlib import Path

    from services import llm, worker

    first = submit(client, pdf_bytes(pages=1)).json['data']['id']
    second = submit(client, pdf_bytes(pages=2)).json['data']['id']
    entered, release = threading.Event(), threading.Event()
    calls = []
    row = json.loads((Path(__file__).parent / 'fixtures/cards-contract-1.jsonl').read_text().splitlines()[0])

    def provider(*args, **kwargs):
        calls.append(threading.current_thread().name)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5), 'first job release timed out'
        return json.dumps([row])

    monkeypatch.setattr(llm, 'complete_block', provider)
    caplog.set_level(logging.INFO, logger='services.worker')
    threads = [threading.Thread(target=worker.drain, args=(client.application,), name=f'drain-{i}')
               for i in range(2)]
    sequence = []
    try:
        threads[0].start()
        assert entered.wait(5)
        threads[1].start()
        # A held provider makes overlap observable; no scheduler-speed assumptions.
        threads[1].join(.25)
        for job_id in (first, second):
            d = client.get(f'/api/upload/jobs/{job_id}').json['data']
            sequence.append((job_id, d['status'], d['stage']))
        assert sequence == [(first, 'cardgen', 'cardgen'), (second, 'queued', 'queued')]
        assert len(calls) == 1
    finally:
        release.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(5)
    for job_id in (first, second):
        d = client.get(f'/api/upload/jobs/{job_id}').json['data']
        sequence.append((job_id, d['status'], d['stage']))
        assert d['status'] == d['stage'] == 'ready'
    assert not any(t.is_alive() for t in threads)
    events = [r.message for r in caplog.records if r.name == 'services.worker']
    assert events.index(f'upload job {first} end status=ready') < events.index(f'upload job {second} start')
    print('upload_jobs.status/stage sequence:', sequence)
    print('worker log:', events)


def test_queued_added_during_run_is_consumed(client, monkeypatch):
    import json
    import threading
    from pathlib import Path

    from services import llm, worker

    entered, release = threading.Event(), threading.Event()
    row = json.loads((Path(__file__).parent / 'fixtures/cards-contract-1.jsonl').read_text().splitlines()[0])
    calls = []

    def provider(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return json.dumps([row])

    monkeypatch.setattr(llm, 'complete_block', provider)
    client.application.config['UPLOAD_WORKER_ENABLED'] = True
    first = submit(client, pdf_bytes(pages=1)).json['data']['id']
    assert entered.wait(5)
    second = submit(client, pdf_bytes(pages=2)).json['data']['id']
    thread = worker.THREADS[id(client.application)]
    try:
        assert client.get(f'/api/upload/jobs/{second}').json['data']['status'] == 'queued'
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    for job_id in (first, second):
        assert client.get(f'/api/upload/jobs/{job_id}').json['data']['status'] == 'ready'


def test_subprocess_restart_after_llm_before_cache(client, tmp_path):
    import json
    import os
    import shutil
    import sqlite3
    import subprocess
    import sys
    import time
    from pathlib import Path

    from data.db import _db_path

    job_id = submit(client, pdf_bytes()).json['data']['id']
    root = Path(client.application.config['UPLOAD_ROOT'])
    baseline_root = tmp_path / 'baseline-uploads'
    shutil.copytree(root, baseline_root)
    baseline_db = tmp_path / 'baseline.sqlite3'
    with client.application.app_context():
        database = _db_path()
        with sqlite3.connect(baseline_db) as copy:
            get_db().backup(copy)
    probe = Path(__file__).with_name('job_restart_process.py')

    def launch(mode, db, uploads):
        env = dict(os.environ, DATABASE_PATH=str(db), UPLOAD_ROOT=str(uploads),
                   UPLOAD_WORKER_ENABLED='0', REVIEW_ISOLATED_RUN='1')
        return subprocess.Popen([sys.executable, str(probe), str(uploads), mode, str(job_id)], env=env)

    process = launch('crash', database, root)
    try:
        deadline = time.monotonic() + 10
        while not (root / 'after-llm-before-cache').exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(.02)
        assert (root / 'after-llm-before-cache').exists()
        assert len(list((root / 'books/restart-probe/cards').glob('*.json'))) == 1
    finally:
        process.kill()
        process.wait(timeout=5)
    killed_db = tmp_path / 'killed.sqlite3'
    with sqlite3.connect(database) as source, sqlite3.connect(killed_db) as copy:
        source.backup(copy)
        persisted = copy.execute('SELECT id,job_id,book_hash,payload,confidence,status,created_at FROM card_drafts ORDER BY id').fetchall()
        assert len(persisted) == 1
    assert launch('resume', database, root).wait(timeout=10) == 0
    with sqlite3.connect(database) as resumed:
        for row in persisted:
            assert resumed.execute('SELECT id,job_id,book_hash,payload,confidence,status,created_at FROM card_drafts WHERE id=?', (row[0],)).fetchone() == row
    assert launch('baseline', baseline_db, baseline_root).wait(timeout=10) == 0
    assert [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()] == ['first', 'second', 'second']
    with sqlite3.connect(database) as actual, sqlite3.connect(baseline_db) as expected:
        # 比较完整行集（id / job_id / book_hash / payload / confidence / status），**排除 created_at**：
        # 本用例把「崩溃+恢复」与「干净基线」两次**独立运行**对拍，墙钟时间天然不同
        # （2026-10-11 二轮只读审实测：只有落在同一秒才偶然相等 ⇒ 原断言 flaky；时间戳不承载本用例要证的口径）。
        cols = 'id, job_id, book_hash, payload, confidence, status'
        rows = actual.execute(f'SELECT {cols} FROM card_drafts ORDER BY id').fetchall()
        assert rows == expected.execute(f'SELECT {cols} FROM card_drafts ORDER BY id').fetchall()
        assert len(rows) == 2
        # 行数仍须逐表一致，防「多写 / 漏写」
        assert actual.execute('SELECT COUNT(*) FROM card_drafts').fetchone() == (2,)
        assert actual.execute('SELECT status FROM upload_jobs WHERE id=?', (job_id,)).fetchone() == ('ready',)


def test_enqueue_at_empty_exit_handshake(client, monkeypatch):
    """drain 刚返回空、线程尚未退出时的通知也必须补消费。"""
    import json
    import threading
    from pathlib import Path

    from services import llm, worker
    original = worker.drain
    empty, release = threading.Event(), threading.Event()
    drains = []

    def held_drain(app):
        original(app)
        drains.append(1)
        if len(drains) == 1:
            empty.set()
            assert release.wait(10)

    row = json.loads((Path(__file__).parent / 'fixtures/cards-contract-1.jsonl').read_text().splitlines()[0])
    monkeypatch.setattr(llm, 'complete_block', lambda *a, **k: json.dumps([row]))
    monkeypatch.setattr(worker, 'drain', held_drain)
    app = client.application
    app.config['UPLOAD_WORKER_ENABLED'] = True
    worker.start(app)
    assert empty.wait(5)
    thread = worker.THREADS[id(app)]
    try:
        job_id = submit(client, pdf_bytes()).json['data']['id']
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    assert len(drains) == 2
    assert client.get(f'/api/upload/jobs/{job_id}').json['data']['status'] == 'ready'


def test_worker_recovers_after_drain_exception(client, monkeypatch, caplog):
    import json
    import threading
    from pathlib import Path

    from services import llm, worker
    original = worker.drain
    exited = threading.Event()
    def broken(app):
        exited.set()
        raise RuntimeError('SECRET BOOK TEXT')
    monkeypatch.setattr(worker, 'drain', broken)
    app = client.application
    app.config['UPLOAD_WORKER_ENABLED'] = True
    worker.start(app)
    assert exited.wait(5)
    with worker.STATE_LOCK:
        thread = worker.THREADS.get(id(app))
    if thread:
        thread.join(5)
    assert id(app) not in worker.THREADS
    assert id(app) not in worker.PENDING
    assert 'SECRET BOOK TEXT' not in caplog.text
    monkeypatch.setattr(worker, 'drain', original)
    row = json.loads((Path(__file__).parent / 'fixtures/cards-contract-1.jsonl').read_text().splitlines()[0])
    monkeypatch.setattr(llm, 'complete_block', lambda *a, **k: json.dumps([row]))
    job_id = submit(client, pdf_bytes(pages=1)).json['data']['id']
    with worker.STATE_LOCK:
        thread = worker.THREADS.get(id(app))
    if thread:
        thread.join(10)
    assert client.get(f'/api/upload/jobs/{job_id}').json['data']['status'] == 'ready'


@pytest.mark.parametrize('failure', ['create', 'start'])
def test_thread_start_failure_then_upload(client, monkeypatch, failure):
    import json
    from pathlib import Path

    from services import llm, worker
    app = client.application
    app.config['UPLOAD_WORKER_ENABLED'] = True
    original = worker.threading.Thread
    def broken(*args, **kwargs):
        if failure == 'create':
            raise RuntimeError('cannot create')
        thread = original(*args, **kwargs)
        thread.start = lambda: (_ for _ in ()).throw(RuntimeError('cannot start'))
        return thread
    monkeypatch.setattr(worker.threading, 'Thread', broken)
    first = submit(client, pdf_bytes()).json['data']['id']
    assert id(app) not in worker.THREADS
    assert id(app) not in worker.PENDING
    monkeypatch.setattr(worker.threading, 'Thread', original)
    row = json.loads((Path(__file__).parent / 'fixtures/cards-contract-1.jsonl').read_text().splitlines()[0])
    monkeypatch.setattr(llm, 'complete_block', lambda *a, **k: json.dumps([row]))
    second = submit(client, pdf_bytes()).json['data']['id']
    with worker.STATE_LOCK:
        thread = worker.THREADS.get(id(app))
    if thread:
        thread.join(10)
    for job in (first, second):
        assert client.get(f'/api/upload/jobs/{job}').json['data']['status'] == 'ready'


def test_enqueue_during_exception_exit(client, monkeypatch):
    import threading

    from services import worker
    entered, release, consumed = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def drain(app):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
            raise RuntimeError('injected')
        consumed.set()
    monkeypatch.setattr(worker, 'drain', drain)
    app = client.application
    app.config['UPLOAD_WORKER_ENABLED'] = True
    worker.start(app)
    assert entered.wait(5)
    thread = worker.THREADS[id(app)]
    worker.start(app)
    release.set()
    thread.join(10)
    assert consumed.is_set() and len(calls) == 2
    assert id(app) not in worker.THREADS and id(app) not in worker.PENDING

@pytest.mark.parametrize('stage', ['extract_text', 'generate_block'])
@pytest.mark.parametrize('exception', [KeyboardInterrupt, BaseException])
def test_round10_concurrent_interrupt_cleanup(client, monkeypatch, caplog, stage, exception):
    import threading

    from services import worker
    app = client.application
    job_id = submit(client, pdf_bytes()).json['data']['id']
    entered, release = threading.Event(), threading.Event()

    def interrupt(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        raise exception('SECRET')

    if stage == 'extract_text':
        monkeypatch.setattr(worker, stage, interrupt)
    else:
        monkeypatch.setattr(worker, 'extract_text', lambda *a: {'path': 'unused'})
        monkeypatch.setattr(worker, 'segment_book', lambda *a: {'blocks': [{}]})
        monkeypatch.setattr(worker.cardgen, stage, interrupt)
    app.config['UPLOAD_WORKER_ENABLED'] = True
    worker.start(app)
    assert entered.wait(5)
    key = id(app)
    thread = worker.THREADS[key]
    try:
        worker.start(app)  # 第二窗口并发通知，必须同时清 PENDING。
        assert key in worker.PENDING
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    assert key not in worker.THREADS and key not in worker.PENDING
    assert 'SECRET' not in caplog.text
    response = client.get(f'/api/upload/jobs/{job_id}')
    assert 'SECRET' not in response.get_data(as_text=True)
    with app.app_context():
        row = get_db().execute('SELECT error FROM upload_jobs WHERE id=?', (job_id,)).fetchone()
        assert 'SECRET' not in str(row['error'])


def test_round14_block_isolation_retry_and_visibility(client, monkeypatch, caplog):
    """Use deterministic blocks while exercising real caches, persistence, API and browser UI."""
    import hashlib
    import json
    import logging
    import os
    import shutil
    import sqlite3
    import tempfile
    from pathlib import Path

    from services import llm, worker
    from services.jobs import get_job

    fixture = Path(__file__).parent / 'fixtures/cards-contract-1.jsonl'
    valid = json.loads(fixture.read_text().splitlines()[0])
    job_id = submit(client, pdf_bytes(pages=3)).json['data']['id']
    root = Path(client.application.config['UPLOAD_ROOT'])
    with client.application.app_context():
        job_hash = get_job(get_db(), job_id, user_id=1)['book_hash']
    blocks = [{'text': str(i), 'text_sha256': hashlib.sha256(str(i).encode()).hexdigest(),
               'book_hash': job_hash, 'chapter': '章'} for i in range(3)]
    original_retries = os.environ.get('UPLOAD_BLOCK_RETRIES')
    caplog.set_level(logging.ERROR, logger='services.worker')
    try:
        for retries in (0, 2):
            # Fresh independent job/temp paths ensure both boundaries are actually executed.
            if retries:
                job_id = submit(client, pdf_bytes(pages=4)).json['data']['id']
                with client.application.app_context():
                    job_hash = get_job(get_db(), job_id, user_id=1)['book_hash']
                blocks = [{**b, 'book_hash': job_hash} for b in blocks]
            with client.application.app_context():
                con = get_db()
                con.execute("UPDATE upload_jobs SET status='cardgen',stage='cardgen' WHERE id=?", (job_id,))
                con.commit()
                monkeypatch.setattr(worker, 'segment_book', lambda *a: {'blocks': blocks})
                calls = {'0': 0, '1': 0, '2': 0}
                def provider(*args, **kwargs):
                    text = json.loads(args[0])['text']
                    calls[text] += 1
                    if text == '1':
                        raise llm.LLMError('PRIVATE BODY')
                    return json.dumps([{**valid, 'question': f'考点：草稿{text}', 'concept_id': f'r14-{text}'}], ensure_ascii=False)
                monkeypatch.setattr(llm, 'complete_block', provider)
                os.environ['UPLOAD_BLOCK_RETRIES'] = str(retries)
                worker.run_job(con, job_id, str(root), user_id=1)
                result = get_job(con, job_id, user_id=1)
                assert result['status'] == 'ready'
                assert '3 块中 1 块未过' in result['error'] and 'provider' in result['error']
                drafts = con.execute('SELECT payload,book_hash FROM card_drafts WHERE job_id=? ORDER BY id', (job_id,)).fetchall()
                assert len(drafts) == 2
                assert {json.loads(r['payload'])['question'] for r in drafts} == {'考点：草稿0', '考点：草稿2'}
                assert all(r['book_hash'] == job_hash for r in drafts)
                assert calls == {'0': 1, '1': retries + 1, '2': 1}
                cache_dir = root / 'books' / job_hash / 'cards'
                cached = list(cache_dir.glob('*.json'))
                assert len(cached) == 2
                assert {p.name.split('-', 1)[0] for p in cached} == {b['text_sha256'] for b in (blocks[0], blocks[2])}
            api = client.get(f'/api/upload/jobs/{job_id}')
            assert api.json['data']['error'] == result['error']
            assert 'PRIVATE BODY' not in api.get_data(as_text=True)

            # Browser integration uses copied temporary DB and upload root only.
            browser_dir = Path(tempfile.mkdtemp(prefix='r14-browser-'))
            browser_db, browser_root = browser_dir / 'browser.sqlite3', browser_dir / 'uploads'
            browser_root.mkdir()
            shutil.copytree(root, browser_root, dirs_exist_ok=True)
            with client.application.app_context(), sqlite3.connect(browser_db) as dest:
                get_db().backup(dest)
            from app import create_app
            app = create_app('development')
            app.config.update(TESTING=True, DATABASE_PATH=str(browser_db), UPLOAD_ROOT=str(browser_root))
            from services import worker as browser_worker
            monkeypatch.setattr(browser_worker, 'start', lambda app: None)
            page = app.test_client().get('/api/upload/jobs/' + str(job_id))
            assert page.json['data']['error'].startswith('3 块中 1 块未过')
            html = app.test_client().get('/').get_data(as_text=True)
            assert 'app.js' in html and 'upload.js' in html
            # Job API value is what showJob renders into the visible upload status node.
            rendered = app.test_client().get(f'/api/upload/jobs/{job_id}').json['data']
            assert rendered['error'] == result['error']
            upload_js = Path('backend/frontend/js/upload.js').read_text()
            assert "d.error ? ' · ' + d.error" in upload_js
            assert rendered['error'] == result['error']
            assert 'PRIVATE BODY' not in caplog.text
    finally:
        if original_retries is None:
            os.environ.pop('UPLOAD_BLOCK_RETRIES', None)
        else:
            os.environ['UPLOAD_BLOCK_RETRIES'] = original_retries
def test_round14_parse_failure_is_classified_parse(client, monkeypatch, caplog):
    """A real oversized source paragraph is reported as parsing, never provider."""
    import logging
    from pathlib import Path

    from services import worker
    from services.jobs import get_job

    job_id = submit(client, pdf_bytes()).json['data']['id']
    root = Path(client.application.config['UPLOAD_ROOT'])
    with client.application.app_context():
        job = get_job(get_db(), job_id, user_id=1)
        raw = root / 'books' / job['book_hash'] / 'raw.md'
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text('正文' * 1100, encoding='utf-8')
        caplog.set_level(logging.ERROR, logger='services.worker')
        worker.run_job(get_db(), job_id, root, user_id=1)
        result = get_job(get_db(), job_id, user_id=1)
        assert result['status'] == 'failed'
        assert result['error'].startswith('parse:')
        assert '正文' not in result['error']
    response = client.get(f'/api/upload/jobs/{job_id}')
    assert response.json['data']['error'].startswith('parse:')
    assert '正文' not in response.get_data(as_text=True)
    assert '正文' not in caplog.text
def test_round14_model_json_parse_is_not_gate(client, monkeypatch):
    from services import cardgen, worker
    from services.jobs import get_job

    job_id = submit(client, pdf_bytes()).json['data']['id']
    root = client.application.config['UPLOAD_ROOT']
    blocks = [{'text': str(i), 'text_sha256': __import__('hashlib').sha256(str(i).encode()).hexdigest(),
               'book_hash': 'irrelevant', 'chapter': '章'} for i in range(3)]
    monkeypatch.setattr(worker, 'extract_text', lambda *a: {'path': 'raw'})
    monkeypatch.setattr(worker, 'segment_book', lambda *a: {'blocks': blocks})
    monkeypatch.setattr(cardgen.llm, 'complete_block', lambda *a, **k: '{invalid json PRIVATE BODY}')
    with client.application.app_context():
        con = get_db()
        for stage, progress in [('extracting', 10), ('segmenting', 20), ('cardgen', 30)]:
            transition(con, job_id, stage, progress, user_id=1)
        worker.run_job(con, job_id, root, user_id=1)
        result = get_job(con, job_id, user_id=1)
    assert result['error'].startswith('parse:')
    assert 'gate' not in result['error'] and 'PRIVATE BODY' not in result['error']

def test_provider_failure_is_provider_and_body_is_private(client, monkeypatch):
    from services import llm, worker
    job_id = submit(client, pdf_bytes()).json['data']['id']
    root = client.application.config['UPLOAD_ROOT']
    monkeypatch.setattr(llm, 'complete_block', lambda *a, **k: (_ for _ in ()).throw(llm.LLMError('PRIVATE BODY')))
    with client.application.app_context():
        con = get_db()
        for stage, progress in [('extracting', 10), ('segmenting', 20), ('cardgen', 30)]:
            transition(con, job_id, stage, progress, user_id=1)
        worker.run_job(con, job_id, root, user_id=1)
        result = get_job(con, job_id, user_id=1)
    assert 'provider' in result['error']
    assert 'PRIVATE BODY' not in result['error']

def test_gate_failure_remains_gate_and_body_is_private(client, monkeypatch):
    from services import worker
    from services.cardgen import CardGateError
    job_id = submit(client, pdf_bytes()).json['data']['id']
    root = client.application.config['UPLOAD_ROOT']
    monkeypatch.setattr(worker.cardgen, 'generate_block', lambda *a: (_ for _ in ()).throw(CardGateError('PRIVATE BODY')))
    with client.application.app_context():
        con = get_db()
        for stage, progress in [('extracting', 10), ('segmenting', 20), ('cardgen', 30)]:
            transition(con, job_id, stage, progress, user_id=1)
        worker.run_job(con, job_id, root, user_id=1)
        result = get_job(con, job_id, user_id=1)
    assert 'gate' in result['error']
    assert 'PRIVATE BODY' not in result['error']


def test_provider_failure_through_llm_layer(client, monkeypatch):
    """强断言：不注入异常类型，让真实 llm 层（HTTP 调用）失败 —— 必须分类为 provider。"""
    import sys
    from types import SimpleNamespace

    from data.db import get_db
    from services import worker
    job_id = submit(client, pdf_bytes()).json['data']['id']
    root = client.application.config['UPLOAD_ROOT']

    def boom_post(*a, **k):
        raise RuntimeError('PRIVATE_BODY_HTTP')

    monkeypatch.setitem(sys.modules, 'requests', SimpleNamespace(post=boom_post))
    with client.application.app_context():
        con = get_db()
        for stage, progress in [('extracting', 10), ('segmenting', 20), ('cardgen', 30)]:
            transition(con, job_id, stage, progress, user_id=1)
        worker.run_job(con, job_id, root, user_id=1)
        r = get_job(con, job_id, user_id=1)
    assert 'provider' in r['error']
    assert 'PRIVATE' not in r['error']
