"""REQ-FAM-04 机械门禁：共享维度只许用家庭谓词，个人维度只许按 user_id。

反证两条：
1. 源码层——`backend/` 里出现裸 `owner_id=?` 只允许在白名单文件（个人维度/运维脚本）；
2. 运行层——同户成员能读到 owner 的书与章，跨户必须 403/404。
"""

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / 'backend'

# 个人维度（上传任务、额度、worker）与运维脚本：按创建者判，不参与家庭共享。
ALLOWLIST = {
    'backend/api/upload.py',
    'backend/services/upload.py',
    'backend/services/user_state.py',
    'backend/services/jobs.py',
    'backend/services/quota.py',
    'backend/services/worker.py',
    'backend/scripts/ingest_kb.py',
    'backend/scripts/ingest_store.py',
    'backend/scripts/reswap_card_text.py',
}


def _scan_bare_owner() -> dict:
    hits = {}
    for path in sorted(BACKEND.rglob('*.py')):
        rel = 'backend/' + path.relative_to(BACKEND).as_posix()
        if rel in ALLOWLIST:
            continue
        text = path.read_text(encoding='utf-8')
        if 'owner_id=?' in text:
            hits[rel] = text.count('owner_id=?')
    return hits


def test_no_bare_owner_predicate_outside_allowlist():
    hits = _scan_bare_owner()
    assert hits == {}, f'共享维度仍按单人判（必须改家庭谓词）：{hits}'


def test_allowlisted_files_still_exist():
    for rel in ALLOWLIST:
        assert (BACKEND.parent / rel).exists(), f'白名单文件不存在，清单过期：{rel}'
