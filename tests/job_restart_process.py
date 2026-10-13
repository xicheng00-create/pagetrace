"""真实子进程探针：在 LLM 已返回、第二块缓存尚未落盘时通知父进程。"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import create_app
from data.db import get_db
from services import cardgen, llm, upload, worker

root, mode, job_id = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
row = json.loads((Path(__file__).parent / 'fixtures/cards-contract-1.jsonl').read_text().splitlines()[0])
blocks = [{'text': text, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
           'book_hash': 'restart-probe', 'chapter': '第1章'} for text in ('first', 'second')]
worker.segment_book = lambda *a: {'blocks': blocks}
upload.now_iso = lambda: '2026-10-11T10:00:00+08:00'

def provider(context, **kwargs):
    text = json.loads(context)['text']
    with (root / 'calls.jsonl').open('a') as stream:
        stream.write(json.dumps(text) + '\n')
    return json.dumps([{**row, 'concept_id': text, 'question': text + row['question']}])

llm.complete_block = provider
original_gate = cardgen.gate

def gate(rows):
    if mode == 'crash' and rows[0]['concept_id'] == 'second':
        (root / 'after-llm-before-cache').touch()
        while True:
            time.sleep(.05)
    return original_gate(rows)

cardgen.gate = gate
app = create_app()
with app.app_context():
    worker.run_job(get_db(), job_id, os.environ['UPLOAD_ROOT'], user_id=1)
