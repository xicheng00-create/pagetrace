"""UP-004：唯一逐块出卡入口；块缓存只保存已过全部闸门的考点。"""
import hashlib
import json
from pathlib import Path

from ai.cardgate import dedup_cards
from ai.cardlen import split_row
from ai.cardtext import to_card
from scripts.ingest_store import REQUIRED, validate_contract

from services import llm


class CardParseError(Exception):
    """Model output could not be parsed as the card JSON contract."""


class CardGateError(ValueError):
    """Card output failed a validation gate."""


PROMPT_VERSION = 'contract-1-cardlen-2'


def validate(row):
    reason = validate_contract(row, 1)
    if reason:
        raise CardGateError('出卡契约不符')
    if any(not isinstance(row[key], str) for key in REQUIRED if key not in ('contract', 'answer_points')):
        raise CardGateError('出卡字段类型不符')
    if any(not isinstance(p, str) or not p.strip() for p in row['answer_points']):
        raise CardGateError('要点必须为非空正文')
    return row


def final_rows(rows):
    for row in rows:
        validate(row)
        if sum(map(len, row['answer_points'])) > 222:
            raise CardGateError('长度闸门拒绝')
    return rows


def gate(rows):
    if rows and all(row.get('_gated') is True for row in rows):
        return final_rows(rows)
    entries = []
    for row in rows:
        validate(row)
        front, back = to_card(row['question'], row['answer_points'])
        entries.append({**row, 'concept_uid': row['concept_id'], 'front': front, 'back': back})
    kept, _, _ = dedup_cards(entries)
    result = []
    for entry in kept:
        row = {k: v for k, v in entry.items() if k not in ('front', 'back', 'concept_uid')}
        names = row.pop('subcards', None)
        for child in split_row(row, names):
            validate(child)
            if sum(map(len, child['answer_points'])) > 222:
                raise CardGateError('长度闸门拒绝')
            result.append({**child, '_gated': True})
    return result


def generate_block(block, root):
    text_hash = hashlib.sha256(block['text'].encode()).hexdigest()
    if text_hash != block['text_sha256']:
        raise CardGateError('块指纹不符')
    path = Path(root) / 'books' / block['book_hash'] / 'cards' / f'{text_hash}-{PROMPT_VERSION}.json'
    if path.exists():
        return final_rows(json.loads(path.read_text()))
    context = json.dumps({'book_hash': block['book_hash'], 'chapter': block['chapter'],
                          'text': block['text']}, ensure_ascii=False)
    raw = llm.complete_block(context, thinking_disabled=True)
    try:
        rows = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise CardParseError('模型 JSON 格式错误') from None
    if not isinstance(rows, list) or not rows:
        raise CardParseError('模型 JSON 结构错误')
    try:
        result = gate(rows)
    except CardGateError:
        raise
    except (TypeError, KeyError, ValueError):
        raise CardGateError('出卡结果未通过全部闸门') from None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)
    return result
