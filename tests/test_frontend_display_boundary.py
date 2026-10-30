"""展示换算与业务推导分界；所有 JS 文件默认拒绝 Math。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / 'backend/frontend/js'
sys.path.insert(0, str(FRONTEND.parents[1]))
MATH_ALLOW = {
    'app.js': {'pct', 'starsOf', 'coverageRing', 'taskRow', 'home', 'renderHome'},
    'flashcard.js': {'touchMove', 'mouseMove', 'finishDrag'},
    'quiz.js': {'head'},
}


def violations(source, filename):
    script = FRONTEND.parents[2] / 'scripts/display_boundary.cjs'
    result = subprocess.run(['node', '--expose-internals', str(script)],
                            input=json.dumps({'source': source, 'allow': list(MATH_ALLOW.get(filename, set()))}),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_display_boundary_all_js():
    assert not [(p.name, violations(p.read_text(), p.name)) for p in FRONTEND.glob('*.js')
                if violations(p.read_text(), p.name)]


@pytest.mark.parametrize('source', [
    "const x = card.subtitle.split(' · ')",
    'const x = card.title.slice(0, 8)',
    'const x = card.text.match(/^.{8}/)',
    'const x = /(.+)/.exec(card.answer)',
    'function judge() { return Math.round(1); }',
])
def test_display_boundary_rejects(source):
    assert violations(source, 'app.js')


@pytest.mark.parametrize('source', [
    "const raw = card.back; const other = raw; other.split('\\n')",
    "const raw = card.book; const x = `${raw} · ${card.chapter}`",
    "const x = card.subtitle; x[['sp','lit'].join('')](' · ')",
])
def test_ast_alias_and_computed_bypasses(source):
    assert violations(source, 'review.js')

@pytest.mark.parametrize('source', [
    'const x = [card.book, card.chapter].join(" · ")',
    'const x = `${card.book} · ${card.chapter}`',
    'const {book} = card; book.split("·")',
    'const x = card.book + "·" + card.chapter',
    'const x = `${esc(card.book)} · ${esc(card.chapter)}`',
])
def test_round10_js_negative(source):
    assert violations(source, 'quiz.js')


def test_round10_js_positive():
    assert not violations('const html = `<span>${esc(x.source_label)}</span>`', 'quiz.js')


def test_round11_display_scope_is_falsifiable(tmp_path):
    """同一 raw split：现匹配器必拦；删去报告的错误实现必放。"""
    source = 'const {book: label} = card; label.split("·")'
    assert violations(source, 'quiz.js')
    script = FRONTEND.parents[2] / 'scripts/display_boundary.cjs'
    broken = tmp_path / 'broken.cjs'
    original = script.read_text()
    mutant = original.replace('bad.add(', 'void (')
    assert mutant != original
    broken.write_text(mutant)
    result = subprocess.run(['node', '--expose-internals', str(broken)],
                            input=json.dumps({'source': source, 'allow': []}),
                            text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == []


def test_round11_display_documented_limit():
    source = 'const key = getFieldName(); card[key].split("·")'
    assert not violations(source, 'quiz.js')
    spec = (FRONTEND.parents[2] / 'DESIGN_SPEC.md').read_text()
    for clause in ('S1-DISPLAY-SCOPE', '运行时计算属性名不保证拦截', '违规处置：阻断合入'):
        assert clause in spec
