"""UP-012：OpenAI 兼容网络单点；本版本不主动连接 local 端点。"""
import fcntl
import json
import os
from pathlib import Path

from config import BaseConfig
from flask import current_app, has_app_context

from services import clock
from services.prompts import messages_for


class LLMError(RuntimeError):
    """Provider/runtime failure; messages intentionally contain no response body."""


class LLMConfigError(ValueError):
    """Invalid local LLM configuration or request contract."""


def config(key, default=None):
    if has_app_context():
        return current_app.config.get(key, default)
    return os.environ.get(key, getattr(BaseConfig, key, default))


def endpoint():
    provider = config('LLM_PROVIDER', 'proxy')
    if provider not in ('proxy', 'official', 'local'):
        raise LLMConfigError('LLM_PROVIDER 必须为 proxy/official/local')
    defaults = {'proxy': 'http://localhost:4000',
                'official': config('DEEPSEEK_BASE_URL'), 'local': 'http://localhost:8080/v1'}
    return str(config('LLM_BASE_URL') or defaults[provider]).rstrip('/')


def usage_path():
    return Path(__file__).resolve().parents[2] / 'data-local' / 'app-usage.jsonl'


def reasoning_tokens(result):
    usage = result.get('usage') or {}
    value = usage.get('reasoning_tokens')
    if value is None:
        value = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens', 0)
    return value


def record_usage(result, model, feature):
    # 白名单字段，不序列化请求、响应正文、错误、凭据；缺失计数明确记 null，不能伪造零用量。
    usage = result.get('usage') or {}
    cached = usage.get('prompt_tokens_details') or {}
    def count(value):
        return value if type(value) is int and value >= 0 else None
    row = {'timestamp': clock.now_iso(), 'model': model, 'feature': feature,
           'prompt_tokens': count(usage.get('prompt_tokens')),
           'prompt_cache_hit_tokens': count(usage.get('prompt_cache_hit_tokens', cached.get('cached_tokens'))),
           'completion_tokens': count(usage.get('completion_tokens')),
           'reasoning_tokens': count(reasoning_tokens(result))}
    path = usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a', encoding='utf-8') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def complete_block(text, *, feature='cardgen', **kwargs):
    return complete(messages_for(feature, text), feature=feature, **kwargs)


def complete(messages, *, base_url=None, model=None, api_key=None, timeout=None,
             thinking_disabled=True, feature="quiz", with_usage=False):
    if feature not in ("quiz", "cardgen", "dedupe", "tutor"):
        raise LLMConfigError("未知 LLM feature")
    if feature in ('cardgen', 'dedupe'):
        if len(messages) != 2 or messages != messages_for(feature, messages[-1].get('content')):
            raise LLMConfigError('出卡/去重必须使用集中固定前缀')
    import requests
    url = base_url or endpoint()
    provider = config('LLM_PROVIDER', 'proxy')
    if timeout is None:
        try:
            timeout = int(config('LLM_TIMEOUT', 30) or 30)
        except (TypeError, ValueError):
            timeout = 30
    key = config('LLM_API_KEY', '') if api_key is None else api_key
    if provider == 'official' and not key:
        key = config('DEEPSEEK_API_KEY', '')
    if feature == 'quiz' and not key and provider != 'local':
        return None
    if feature == 'tutor' and not key and provider != 'local':
        # 无 key 时 tutor 退成「只给库内原文」（ai/tutor.py 的 fallback），不去打一次注定 401 的请求。
        return (None, {}) if with_usage else None
    payload = {'model': model or config('LLM_MODEL'), 'messages': messages, 'temperature': 0.4}
    # 关思考只对懂这个字段的档位发（proxy/official）；local 档（Ollama/LM Studio/vLLM 等）不认
    # 非标准字段，硬塞可能 400。local 档也不拒绝 reasoning_tokens：本地推理不花钱，
    # 关不掉思考就不该因此判失败。
    clamp_thinking = thinking_disabled and provider in ('proxy', 'official')
    if clamp_thinking:
        # 2026-10-11 实测：经本地 LiteLLM(proxy 档) 时顶层 thinking 不生效——deepseek-flash 仍产出
        # 4059 reasoning token 触发拒绝；改用 extra_body 透传后 reasoning_tokens=null。官方档认顶层 thinking。
        if provider == 'proxy':
            payload['extra_body'] = {'thinking': {'type': 'disabled'}}
        else:
            payload['thinking'] = {'type': 'disabled'}
    result = {}
    failed = False
    try:
        response = requests.post(f"{url.rstrip('/')}/chat/completions",
                                 headers={'Authorization': f'Bearer {key}'},
                                 json=payload, timeout=timeout)
        result = response.json()
        response.raise_for_status()
    except Exception:
        failed = True
    try:
        record_usage(result, payload['model'], feature)
    except Exception:
        failed = True
    if failed:
        # 供应商错误可能回显书文；不得传播原始异常或正文。无 usage 的失败调用计数记 null。
        raise LLMError('LLM 调用或用量落账失败') from None
    if clamp_thinking and reasoning_tokens(result):
        raise LLMError('模型返回 reasoning_tokens > 0，拒绝采纳')
    content = result['choices'][0]['message']['content']
    if with_usage:
        # 只有拿到真实 usage 才回传；缺字段就是空 dict，调用方据此记 NULL 而不是造假 0。
        return content, result.get('usage') or {}
    return content
