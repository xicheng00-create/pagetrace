import hashlib
import json
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ai.cardlen import cut_points, split_line, split_long, split_row

FIXTURES = list((Path(__file__).parent / 'fixtures/cardlen').glob('*.json'))
FIXTURES = [p for p in FIXTURES if p.stem != 'provenance']

# 新口径（2026-10-13，owner 拍板方案 A）：切点只落在配对括号/引号之外，按 句末 → 分号 → 逗号
# 三级降级；三级都切不动 → **原样放行**（宁可这张卡长，不可让人读不通）。
# 故「每张卡 ≤222」不是绝对断言：无可用切点时的超长卡是合规的。
CUT_LEVELS = ('。！？…', '；', '，、:：')


def over_cap_allowed(text, cap=222):
    """超 cap 仅当该段在配对括号/引号外无可用切点时才合法（原样放行，禁止按 cap 硬切）。"""
    return len(text) > cap and not cut_points(text, CUT_LEVELS)


def samples():
    for path in FIXTURES:
        f = json.loads(path.read_text())
        yield f, json.loads(f['input']), split_line(f['input'], f['names'])


def test_no_overlong_rows():
    for _, _, lines in samples():
        for l in lines:
            back = ''.join(json.loads(l)['answer_points'])
            assert len(back) <= 222 or over_cap_allowed(back), back[:60]


def test_exact_reconstruction():
    for _, row, lines in samples():
        assert ''.join(p for l in lines for p in json.loads(l)['answer_points']) == ''.join(row['answer_points'])


def test_contiguous_coverage():
    for fixture, row, lines in samples():
        original, pos = ''.join(row['answer_points']), 0
        cuts = []
        for line in lines[:-1]:
            points = json.loads(line)['answer_points']
            cuts.append((sum(map(len, points)), points[-1][-1]))
        expected_cuts = fixture['expected_cut_count']
        assert len(cuts) == expected_cuts and expected_cuts > 0, 'fixture must contain expected non-empty cut points'
        for cut, marker in cuts:
            assert marker in '。！？；，、', f'illegal cut at {cut}: {marker!r}'
        for line in lines:
            for point in json.loads(line)['answer_points']:
                assert original.find(point, pos) == pos
                pos += len(point)
        assert pos == len(original)


def test_unchanged_and_inherited():
    for _, row, lines in samples():
        for line in lines:
            for key in ('contract', 'concept_id', 'subject', 'book', 'chapter'):
                assert json.loads(line)[key] == row[key]
        row['answer_points'] = ['原文。']
        line = json.dumps(row, ensure_ascii=False, indent=1)
        assert split_line(line) == [line]
        assert split_row(row) == [row]


def test_idempotent():
    for f, _, lines in samples():
        assert lines == split_line(f['input'], f['names'])


def test_kb_bytes_equal():
    for f, _, lines in samples():
        assert hashlib.sha256(('\n'.join(lines)+'\n').encode()).digest() == hashlib.sha256(('\n'.join(f['expected'])+'\n').encode()).digest()


def test_punctuation_and_rejections():
    assert ''.join(split_long('甲。'*150)) == '甲。'*150
    # 新口径：括号/引号外无可用切点 → 原样放行（旧口径在此 raise ValueError，或按 cap 硬切造残句）
    assert split_long('甲'*223) == ['甲'*223]
    assert over_cap_allowed('甲'*223)
    # 命名缺失/不完整 → 确定性兜底命名，不丢整块（2026-10-11 真跑实测：模型 subcards=null 曾致整块被拒）
    row = {'title': '标题', 'question': '为什么？', 'answer_points': ['甲。'*150]}
    packed = split_long('甲。'*150)
    out = split_row(row)
    assert len(out) == len(packed)
    assert all(len(p) <= 222 or over_cap_allowed(p) for r in out for p in r['answer_points'])
    assert ''.join(p for r in out for p in r['answer_points']) == '甲。'*150
    assert all(r['title'].startswith('标题 · ') and r['question'] for r in out)
    assert len({r['title'] for r in out}) == len(out)
    assert [r['title'] for r in split_row(row, [{}]*len(packed))] == [r['title'] for r in out]


@pytest.mark.parametrize('names', [None, [None, None], [{'name': 'A'}],
                                  [{'name': '有效', 'question': '有效问句？'}], [3], 'bad'])
def test_names_fallback_per_item(names):
    from ai.cardlen import groups
    row = {'title': '标题', 'question': '为什么？', 'answer_points': ['甲。'*200]}
    out = split_row(row, names)
    assert len(out) == len(groups(row))
    assert ''.join(p for r in out for p in r['answer_points']) == ''.join(row['answer_points'])
    if isinstance(names, list) and isinstance(names[0], dict) and 'question' in names[0]:
        assert out[0]['title'] == '标题 · 有效'
        assert out[0]['question'] == '有效问句？'


def test_fallback_name_uniqueness_is_block_local():
    """Deterministic suffixes are local to one split block, not global IDs."""
    row = {'title': '标题', 'question': '为什么？', 'answer_points': ['甲。'*200]}
    first = split_row(row)
    second = split_row(row)
    assert [r['title'] for r in first] == [r['title'] for r in second]
    assert len({r['title'] for r in first}) == len(first)
    # Identical blocks may have identical fallback names; global uniqueness is not promised.
    assert [r['title'] for r in first] == [r['title'] for r in second]
