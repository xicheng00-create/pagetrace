import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from services import llm


def test_single_outbound_point():
    root = Path(__file__).resolve().parents[1] / 'backend'
    for path in root.rglob('*.py'):
        if path != root / 'services/llm.py':
            assert 'chat/completions' not in path.read_text(), path


def test_provider_switch(monkeypatch):
    # 显式置空而非 delenv：config() 无 app 上下文时回落 BaseConfig（其值在 import 时已从 settings.local 捕获），
    # delenv 会「回落」到 settings.local 的真实接线 → 与 settings.local 内容耦合。空串才是「显式无覆写」。
    monkeypatch.setenv('LLM_BASE_URL', '')
    for provider, url in [('proxy', 'http://localhost:4000'),
                          ('official', llm.config('DEEPSEEK_BASE_URL')),
                          ('local', 'http://localhost:8080/v1')]:
        monkeypatch.setenv('LLM_PROVIDER', provider)
        assert llm.endpoint() == url
    monkeypatch.setenv('LLM_BASE_URL', 'http://localhost:9999/v1/')
    assert llm.endpoint() == 'http://localhost:9999/v1'
    monkeypatch.setenv('LLM_PROVIDER', 'bad')
    with pytest.raises(ValueError):
        llm.endpoint()


def test_payload_thinking_disabled(monkeypatch):
    bodies = []
    def post(url, **kwargs):
        bodies.append((url, kwargs['json']))
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {'choices': [{'message': {'content': 'ok'}}]})
    monkeypatch.setitem(sys.modules, 'requests', SimpleNamespace(post=post))
    monkeypatch.setenv('LLM_API_KEY', 'mock-key')
    monkeypatch.delenv('LLM_PROVIDER', raising=False)
    assert llm.complete([{'role': 'user', 'content': 'x'}]) == 'ok'
    # proxy 档（默认）：LiteLLM 只认 extra_body 透传；顶层 thinking 实测无效
    assert bodies[0][1]['extra_body']['thinking'] == {'type': 'disabled'}
    assert 'thinking' not in bodies[0][1]
    monkeypatch.setenv('LLM_PROVIDER', 'official')
    assert llm.complete([{'role': 'user', 'content': 'x'}]) == 'ok'
    assert bodies[1][1]['thinking'] == {'type': 'disabled'}


def test_reasoning_rejected(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "mock-key")
    monkeypatch.setitem(sys.modules, 'requests', SimpleNamespace(post=lambda *a, **k:
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'usage': {'completion_tokens_details': {'reasoning_tokens': 1}}})))
    with pytest.raises(llm.LLMError, match='reasoning_tokens'):
        llm.complete([])


@pytest.mark.skipif(getattr(os, "environ").get('LLM_PROVIDER') != 'local', reason='本版 local 默认不接入；零网络')
def test_local_smoke_skipped_by_default(monkeypatch):
    # 本版 smoke 只验接口与 mock，不连接任何外部机器。
    monkeypatch.setitem(sys.modules, 'requests', SimpleNamespace(post=lambda *a, **k:
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'choices': [{'message': {'content': 'local-interface-ok'}}]})))
    assert llm.complete([]) == 'local-interface-ok'


def fake_response(monkeypatch, bodies, usage=None):
    def post(url, **kwargs):
        bodies.append(kwargs['json'])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'choices': [{'message': {'content': 'PRIVATE_OUTPUT'}}],
            'usage': usage or {'prompt_tokens': 20, 'prompt_cache_hit_tokens': 15,
                               'completion_tokens': 3,
                               'completion_tokens_details': {'reasoning_tokens': 0}},
            'model': 'PRIVATE_RESPONSE_MODEL'})
    monkeypatch.setitem(sys.modules, 'requests', SimpleNamespace(post=post))


def test_prompt_prefix_stable(monkeypatch):
    import hashlib
    import json
    from services.prompts import PREFIXES
    bodies = []
    fake_response(monkeypatch, bodies)
    for feature in ('cardgen', 'dedupe'):
        for block in ('PRIVATE_BLOCK_A', 'PRIVATE_BLOCK_B'):
            llm.complete_block(block, feature=feature)
        prefixes = [json.dumps(b['messages'][:-1], ensure_ascii=False).encode()
                    for b in bodies[-2:]]
        assert hashlib.sha256(prefixes[0]).digest() == hashlib.sha256(prefixes[1]).digest()
        assert bodies[-1]['messages'][0] == {'role': 'system', 'content': PREFIXES[feature]}
        assert bodies[-1]['messages'][-1]['content'] == 'PRIVATE_BLOCK_B'


def test_usage_logged(monkeypatch):
    import json
    fake_response(monkeypatch, [])
    llm.complete_block('PRIVATE_BOOK')
    rows = llm.usage_path().read_text().splitlines()
    assert len(rows) == 1
    row = json.loads(rows[0])
    assert set(row) == {'timestamp', 'model', 'feature', 'prompt_tokens',
                        'prompt_cache_hit_tokens', 'completion_tokens', 'reasoning_tokens'}
    assert row['feature'] == 'cardgen'
    assert row['prompt_cache_hit_tokens'] == 15
    assert row['prompt_tokens'] == 20 and row['completion_tokens'] == 3
    assert row['reasoning_tokens'] == 0
    assert llm.usage_path().stat().st_mode & 0o777 == 0o600
    fake_response(monkeypatch, [], {'prompt_tokens_details': {'cached_tokens': 7},
                                   'prompt_tokens': 'PRIVATE_USAGE'})
    llm.complete_block('PRIVATE_BOOK', feature='dedupe')
    row = json.loads(llm.usage_path().read_text().splitlines()[-1])
    assert row['prompt_cache_hit_tokens'] == 7 and row['prompt_tokens'] is None


def test_no_body_in_log(monkeypatch, caplog):
    fake_response(monkeypatch, [])
    llm.complete_block('PRIVATE_BOOK')
    assert 'PRIVATE' not in llm.usage_path().read_text() + caplog.text
    monkeypatch.setitem(sys.modules, 'requests', SimpleNamespace(post=lambda *a, **k:
        (_ for _ in ()).throw(RuntimeError('PRIVATE_BOOK'))))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete_block('PRIVATE_BOOK')
    assert 'PRIVATE' not in str(exc.value) + caplog.text


def test_usage_before_reasoning_rejection(monkeypatch):
    import json
    fake_response(monkeypatch, [], {'completion_tokens_details': {'reasoning_tokens': 4}})
    with pytest.raises(llm.LLMError, match='reasoning_tokens'):
        llm.complete_block('PRIVATE_BOOK')
    assert json.loads(llm.usage_path().read_text())['reasoning_tokens'] == 4
    with pytest.raises(ValueError, match='feature'):
        llm.complete([], feature='PRIVATE_BOOK')


def test_prefix_bypass_rejected():
    with pytest.raises(ValueError, match='固定前缀'):
        llm.complete([{'role': 'system', 'content': 'dynamic'}], feature='cardgen')


def test_ledger_failure_rejects_output(monkeypatch):
    fake_response(monkeypatch, [])
    monkeypatch.setattr(llm, 'record_usage', lambda *args:
                        (_ for _ in ()).throw(OSError('PRIVATE_BOOK')))
    with pytest.raises(llm.LLMError, match='落账失败') as exc:
        llm.complete_block('PRIVATE_BOOK')
    assert 'PRIVATE' not in str(exc.value)


def test_quiz_provider_has_no_legacy_bypass(monkeypatch):
    from services import quizgen
    bodies = []
    fake_response(monkeypatch, bodies)
    monkeypatch.setenv('LLM_API_KEY', 'mock-key')
    monkeypatch.setenv('LLM_MODEL', 'selected-model')
    monkeypatch.setenv('LLM_PROVIDER', 'proxy')
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'https://legacy.invalid')
    assert quizgen._chat([{'role': 'user', 'content': 'question'}]) == 'PRIVATE_OUTPUT'
    assert bodies[0]['model'] == 'selected-model'
    assert 'DEEPSEEK_' not in quizgen._chat.__code__.co_consts


def test_official_key_resolved_by_adapter(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'official')
    monkeypatch.setenv('LLM_API_KEY', '')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'mock-key')
    fake_response(monkeypatch, [])
    assert llm.complete([]) == 'PRIVATE_OUTPUT'


@pytest.mark.parametrize('usage', [{'reasoning_tokens': 5},
    {'reasoning_tokens': 5, 'completion_tokens_details': {'reasoning_tokens': 0}},
    {'reasoning_tokens': None, 'completion_tokens_details': {'reasoning_tokens': 5}}])
def test_top_level_reasoning_rejected_and_logged(monkeypatch, usage):
    import json
    monkeypatch.setenv('LLM_PROVIDER', 'proxy')
    fake_response(monkeypatch, [], usage)
    with pytest.raises(llm.LLMError, match='reasoning_tokens'):
        llm.complete_block('正文')
    assert json.loads(llm.usage_path().read_text())['reasoning_tokens'] == 5


def test_proxy_provider_without_key_warns_at_boot(tmp_path):
    """UP-012 接线自检：provider=proxy 但 LLM_API_KEY 为空 → 启动必须 WARNING。

    背景（2026-10-11）：settings.local 缺 LLM_* 接线时上游 401，且异常被收敛成 `job failed`（原文不入日志），
    真跑现场极难定位。此断言把「静默失败」变成「启动即出声」。
    """
    import subprocess
    repo = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in getattr(os, "environ").items() if k not in ('FLASK_ENV',)}
    env['LLM_PROVIDER'] = 'proxy'
    env['LLM_API_KEY'] = ''
    out = subprocess.run(
        [sys.executable, '-c', "import sys; sys.path.insert(0, 'backend'); import app; app.create_app('development')"],
        cwd=str(repo), env=env, capture_output=True, text=True, timeout=120)
    assert 'LLM_API_KEY 为空' in (out.stdout + out.stderr), out.stdout + out.stderr
