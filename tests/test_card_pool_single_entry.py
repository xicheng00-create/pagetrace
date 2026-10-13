"""UP-006：扫描全部 backend Python，例外只到指定函数/操作。"""
import ast
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(BACKEND))
# 具名卡池入口；新函数必须显式评审，不整文件放行。
POOL_FUNCTIONS = '''due_query new_query today_queue books_with_pool_counts cards_for_concept
concept_status_counts concepts_with_card_counts scheduled_plan_cards card_status
level_card_statuses subject_pool_counts subject_last_review learned_quiz_cards card_answer
wrong_answer_cards chapter_answer_pool card_content_hash current_cached_quiz_item
quiz_card_context weak_chapter_card_rows update_card_schedule card_schedule
available_due_count available_new_count chapter_pool_counts'''.split()
ALLOW = {('services/cards.py', name): {'FROM', 'JOIN', 'UPDATE'} for name in POOL_FUNCTIONS}
ALLOW.update({('services/card_quiz_pool.py', name): {'FROM', 'JOIN', 'UPDATE'}
              for name in ['learned_quiz_cards', 'card_answer', 'wrong_answer_cards', 'chapter_answer_pool', 'card_content_hash', 'current_cached_quiz_item', 'quiz_card_context', 'weak_chapter_card_rows', 'update_card_schedule', 'card_schedule', 'available_due_count', 'available_new_count', 'chapter_pool_counts']})
ALLOW.update({
    ('services/nav.py', 'parent_of'): {'FROM'},  # 只读实体父级，不读卡池/调度；test_nav query_only 反证
    ('services/cards.py', '_FROM'): {'FROM'},
    ('data/models.py', 'migrate'): {'FROM'},  # 历史题目指纹回填
    ('services/upload.py', 'confirm_drafts'): {'INTO'},  # 用户显式确认的事务
    ('scripts/ingest_kb.py', 'ingest_file'): {'FROM', 'INTO', 'UPDATE'},  # 契约导入
    ('scripts/migrate_status_reviewing.py', 'main'): {'FROM', 'UPDATE'},
    ('scripts/refresh_stale_quiz_items.py', 'stale_rows'): {'JOIN'},
    ('scripts/reswap_card_text.py', 'main'): {'FROM', 'UPDATE'},
})
SQL = re.compile(r'\b(FROM|JOIN|UPDATE|INTO)\s+(?:(?:["`\[]?\w+["`\]]?)\s*\.\s*)?["`\[]?cards\b', re.I)


def scan(path, relative):
    tree = ast.parse(path.read_text())
    symbols = {}

    def text(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return symbols.get(node.id, '__DYNAMIC_TABLE__')
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Dict):
                return ' '.join(text(v) for v in node.value.values)
            return text(node.value)
        if isinstance(node, (ast.List, ast.Tuple)):
            return ' '.join(text(v) for v in node.elts)
        if isinstance(node, ast.Dict):
            return ' '.join(text(v) for v in node.values)
        if isinstance(node, ast.IfExp):
            return text(node.body) + ' ' + text(node.orelse)
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Add):
                return text(node.left) + text(node.right)
            if isinstance(node.op, ast.Mod):
                args = tuple(text(v) for v in node.right.elts) if isinstance(node.right, ast.Tuple) else text(node.right)
                try:
                    return text(node.left) % args
                except (TypeError, ValueError):
                    return text(node.left)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = next((v for v in ast.walk(tree) if isinstance(v, ast.FunctionDef) and v.name == node.func.id), None)
            if function:
                return ' '.join(text(v.value) for v in ast.walk(function) if isinstance(v, ast.Return))
            return '__DYNAMIC_TABLE__'
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = text(node.func.value)
            if node.func.attr == 'dedent' and node.args:
                return text(node.args[0])
            if node.func.attr == 'format':
                try:
                    return base.format(*(text(v) for v in node.args),
                                       **{v.arg: text(v.value) for v in node.keywords})
                except (IndexError, KeyError, ValueError):
                    return base
            if node.func.attr == 'join' and node.args:
                return base.join(text(v) for v in node.args[0].elts) if isinstance(node.args[0], (ast.List, ast.Tuple)) else text(node.args[0])
        if isinstance(node, ast.JoinedStr):
            return ''.join(text(v.value) if isinstance(v, ast.FormattedValue) else text(v)
                           for v in node.values)
        return ''

    # 全树定点求值，不受函数定义/调用顺序影响；分支合并保守扫描。
    for _ in range(10):
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple) and isinstance(node.iter, (ast.List, ast.Tuple)):
                for i, target in enumerate(node.target.elts):
                    if isinstance(target, ast.Name):
                        symbols[target.id] = ' '.join(text(row.elts[i]) for row in node.iter.elts if isinstance(row, ast.Tuple))
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        symbols[target.id] = text(node.value)
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                symbols[node.target.id] = symbols.get(node.target.id, '') + text(node.value)
    offenders = set()

    def visit(node, scope='<module>'):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = node.name
        if isinstance(node, ast.Assign):
            if scope == '<module>' and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                scope = node.targets[0].id
        value = text(node)
        for match in re.finditer(SQL.pattern + r'|\b(FROM|JOIN|UPDATE|INTO)\s+__DYNAMIC_TABLE__', value, re.I):
            operation = (match[1] or match[2]).upper()
            if operation not in ALLOW.get((relative, scope), set()):
                offenders.add(f'{relative}:{node.lineno}:{scope}:{operation}: {value.strip()}')
        for child in ast.iter_child_nodes(node):
            visit(child, scope)
    visit(tree)
    return sorted(offenders)


def test_card_pool_single_entry():
    offenders = [item for path in sorted(BACKEND.rglob('*.py'))
                 for item in scan(path, path.relative_to(BACKEND).as_posix())]
    assert not offenders, 'card pool SQL bypass: ' + ', '.join(offenders)


@pytest.mark.parametrize('relative,source', [
    ('scripts/new_probe.py', 'def probe(c):\n c.execute("SELECT * FROM cards")'),
    ('app.py', 'def probe(c):\n c.execute("SELECT * FROM main.cards")'),
    ('services/upload.py', 'def probe(c):\n t="cards"\n c.execute(f"SELECT * FROM {t}")'),
    ('services/upload.py', 'def probe(c):\n c.execute("SELECT * FR" + "OM " + "cards")'),
])
def test_scanner_rejects_bypass(tmp_path, relative, source):
    path = tmp_path / 'probe.py'
    path.write_text(source)
    assert scan(path, relative), (relative, source)

@pytest.mark.parametrize('source', [
    '''exec("c.execute('SELECT * FROM %s')" % "cards")''',
    '''eval("c.execute('SELECT * FROM {}')".format("cards"))''',
    'getattr(c, "execute")("SELECT * FROM %s" % "cards")',
    'c.execute("SELECT * FROM {}".format("cards"))',
    'c.execute(" ".join(["SELECT * FROM", "cards"]))',
    'c.execute("WITH x AS (SELECT * FROM other) SELECT * FROM x\\n JOIN cards AS c ON 1=1")',
])
def test_scanner_dynamic_sql(tmp_path, source):
    path = tmp_path / 'dynamic.py'
    path.write_text(source)
    assert scan(path, 'services/probe.py'), source


@pytest.mark.parametrize('source', [
    'def later():\n return TABLE\nTABLE="cards"\nc.execute("SELECT * FROM " + TABLE)',
    'q="SELECT * FROM "\nq += "cards"\nc.execute(q)',
    'c.execute("".join(["SELECT * FR", "OM cards"]))',
    'c.execute("SELECT * FROM cards" if flag else "SELECT 1")',
    'parts={"table":"cards"}\nc.execute("SELECT * FROM " + parts["table"])',
    'c.execute(textwrap.dedent("SELECT * FROM cards"))',
    'con.executescript("SELECT * FROM cards;")',
    'con.row_factory=sqlite3.Row\nr=con.execute("SELECT * FROM cards").fetchone()\nx=r["front"]',
])
def test_round7_scanner_cases(tmp_path, source):
    path = tmp_path / 'probe.py'
    path.write_text(source)
    assert scan(path, 'services/probe.py')

@pytest.mark.parametrize('source', [
    'def probe(c, table):\n c.execute("SELECT * FROM " + table)',
    'def _table():\n return "cards"\nc.execute("SELECT * FROM " + _table())',
    'def probe(c, table):\n sql="SELECT * FROM "\n sql += table\n c.execute(sql)',
    'parts=["SELECT * FROM " + table]\nc.execute(" AND ".join(parts))',
    'def probe(c, table):\n c.execute(f"SELECT * FROM {table}")',
    'def probe(c, table):\n c.execute("SELECT * FROM %s" % table)',
])
def test_round10_sql_negative(tmp_path, source):
    path = tmp_path / 'probe.py'
    path.write_text(source)
    hits = scan(path, 'services/probe.py')
    assert hits
    assert all('services/probe.py:' in hit and 'SELECT' in hit for hit in hits)


@pytest.mark.parametrize('relative,source', [
    ('services/probe.py', 'c.execute("SELECT * FROM books WHERE id=?", (book_id,))'),
    ('services/cards.py', 'def card_answer(c, id):\n return c.execute("SELECT back FROM cards WHERE id=?", (id,))'),
])
def test_round10_sql_positive(tmp_path, relative, source):
    path = tmp_path / 'probe.py'
    path.write_text(source)
    assert not scan(path, relative)


def test_round11_sql_scope_is_falsifiable(tmp_path, monkeypatch):
    """同一 cards 拼接：现扫描必拦；删除 cards 规则的错误实现必放。"""
    path = tmp_path / 'probe.py'
    path.write_text('c.execute("SELECT * FROM " + "cards")')
    assert scan(path, 'services/probe.py')
    monkeypatch.setattr(sys.modules[__name__], 'SQL', re.compile(r'(?!)()'))
    assert not scan(path, 'services/probe.py')


def test_round11_sql_documented_limit(tmp_path):
    path = tmp_path / 'probe.py'
    path.write_text('table="books"\nc.execute("SELECT * FROM " + table)')
    assert not scan(path, 'services/probe.py')
    spec = (BACKEND.parent / 'DESIGN_SPEC.md').read_text()
    for clause in ('S1-SQL-SCOPE', '非 cards 的已知表名拼接不保证拦截', '违规处置：阻断合入'):
        assert clause in spec
