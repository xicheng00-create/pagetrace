import re

CANONICAL_PREDICATE = re.compile(
    r'b\.owner_id IN \(SELECT u2\.id FROM users u2 '
    r'WHERE u2\.household_id=\(SELECT u1\.household_id FROM users u1 WHERE u1\.id=\?\)\)'
)


def strip_tenant(query: str) -> str:
    """去掉规范家庭谓词，用来证明门禁会转红。"""
    return CANONICAL_PREDICATE.sub('1=1', query, count=1)
"""SQL scope gate negative cases; unresolved expressions must never silently pass."""
import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'scripts/s2_sql_scope_scan.py'
spec = importlib.util.spec_from_file_location('s2_scope_gate', path)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.mark.parametrize('source', [
    'con.execute("SELECT * FROM books")',
    'con.execute("SELECT owner_id FROM books WHERE id=?", (book_id,))',
    'table="books"\ncon.execute("SELECT * FROM " + table)',
    'sql="SELECT * FROM books"\ncon.execute(sql)',
    'con.execute(f"SELECT * FROM {table}")',
    'con.execute("SELECT * FROM books WHERE owner_id=?")',
    'con.execute("SELECT * FROM books WHERE owner_id=?" + suffix, (uid,))',
    'con.executescript("SELECT * FROM books;")',
])
def test_bad_sql_is_rejected(source):
    assert gate.scan(source, 'backend/services/probe.py')


@pytest.mark.parametrize('source', [
    'con.execute("SELECT * FROM books WHERE owner_id=?", (uid,))',
    'sql="SELECT * FROM books WHERE owner_id=?"\ncon.execute(sql, (uid,))',
    'con.execute("SELECT * FROM prefs WHERE user_id=? AND key=?", (uid,key))',
    'con.execute("SELECT name FROM subjects WHERE id=?", (sid,))',
    'con.execute("INSERT INTO prefs(user_id,key,value) VALUES(?,?,?)", (uid,key,value))',
])
def test_bound_sql_is_accepted(source):
    assert not gate.scan(source, 'backend/services/probe.py')


def test_offline_migration_exemption_is_not_a_service_exemption():
    source = 'con.execute("SELECT * FROM card_reviews")'
    assert not gate.scan(source, 'backend/scripts/migrate_status_reviewing.py')
    assert gate.scan(source, 'backend/services/migrate_status_reviewing.py')


@pytest.mark.parametrize('source', [
    'con.execute("SELECT * FROM books WHERE owner_id=?", (book_id,))',
    'con.execute("SELECT * FROM books WHERE owner_id=?", (1,))',
    'con.execute("SELECT * FROM books WHERE id=? AND owner_id=?", (uid,book_id))',
    'con.execute("SELECT * FROM books WHERE id=? AND owner_id=?", (book_id,))',
])
def test_wrong_tenant_parameter_slot_is_rejected(source):
    assert gate.scan(source, 'backend/services/probe.py')


def test_correct_second_tenant_parameter_slot_is_accepted():
    assert not gate.scan(
        'con.execute("SELECT * FROM books WHERE id=? AND owner_id=?", (book_id,uid))',
        'backend/services/probe.py')


def test_placeholder_generator_is_resolved_but_table_generator_is_not():
    safe = "marks=','.join('?' for _ in ids)\ncon.execute(f'SELECT * FROM books WHERE owner_id=? AND id IN ({marks})', [uid,*ids])"
    assert not gate.scan(safe, 'backend/services/probe.py')
    unsafe = "marks=','.join(table for table in tables)\ncon.execute(f'SELECT * FROM {marks} WHERE owner_id=?', [uid])"
    assert gate.scan(unsafe, 'backend/services/probe.py')


def test_tuple_query_dictionary_scans_sql_not_labels():
    source = "queries={'book':('SELECT id FROM books WHERE owner_id=?','label',None)}\nsql,label,parent=queries[page]\ncon.execute(sql,(uid,))"
    assert not gate.scan(source, 'backend/services/probe.py')
    assert gate.scan(source.replace(' WHERE owner_id=?', ''), 'backend/services/probe.py')


def test_repeated_placeholder_string_is_resolved():
    source = "marks=','.join('?' * len(ids))\ncon.execute(f'SELECT * FROM books WHERE owner_id=? AND id IN ({marks})', [uid,*ids])"
    assert not gate.scan(source, 'backend/services/probe.py')


@pytest.mark.parametrize('name', [
    'learned_quiz_cards', 'weak_chapter_card_rows',
    'available_due_count', 'available_new_count',
])
def test_card_pool_data_filters_are_resolved_and_tenant_removal_is_red(name):
    import ast
    source = (path.parents[1] / 'backend/services/card_quiz_pool.py').read_text()
    function = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef) and n.name == name)
    query = ast.get_source_segment(source, function)
    assert not gate.scan(query, 'backend/services/card_quiz_pool.py')
    bad = strip_tenant(query).replace('qa.user_id = ?', '1=1').replace('cr.user_id=?', '1=1')
    assert gate.scan(bad, 'backend/services/card_quiz_pool.py')


@pytest.mark.parametrize('sql', [
    'CREATE TABLE books(id); SELECT * FROM books;',
    'CREATE TABLE x AS SELECT * FROM books;',
    'CREATE TABLE x(id); INSERT INTO books VALUES(1);',
])
def test_ddl_prefix_does_not_hide_data_queries(sql):
    assert gate.scan(f'con.executescript({sql!r})', 'backend/services/probe.py')


def test_schema_static_proof_rejects_embedded_query_and_unknown_builder(tmp_path):
    import shutil

    from s2_schema_sql_proof import ddl_only, schema_sql
    root = path.parents[1]
    destination = tmp_path / 'backend/data'
    destination.mkdir(parents=True)
    for name in ('models.py', 's2_schema.py'):
        shutil.copyfile(root / 'backend/data' / name, destination / name)
    assert ddl_only(schema_sql(tmp_path))
    assert ddl_only(schema_sql(tmp_path, fresh=True))
    model = destination / 'models.py'
    model.write_text(model.read_text().replace('CREATE TABLE IF NOT EXISTS users',
                                             'SELECT * FROM books; CREATE TABLE IF NOT EXISTS users'))
    assert not ddl_only(schema_sql(tmp_path))
    # Fresh schema is independent, not a runtime transformation of legacy SQL.
    assert ddl_only(schema_sql(tmp_path, fresh=True))
    builder = destination / 's2_schema.py'
    builder.write_text(builder.read_text().replace('CREATE TABLE IF NOT EXISTS users',
                                                 'SELECT * FROM books; CREATE TABLE IF NOT EXISTS users'))
    assert not ddl_only(schema_sql(tmp_path, fresh=True))
    builder.write_text(builder.read_text().replace('FRESH_SCHEMA = """', 'FRESH_SCHEMA = unknown + """'))
    with pytest.raises(ValueError, match='literal string'):
        schema_sql(tmp_path, fresh=True)


def test_level_filter_is_resolved_and_wrong_tenant_binding_fails():
    import ast
    source = (path.parents[1] / 'backend/services/cards.py').read_text()
    fn = next(n for n in ast.parse(source).body
              if isinstance(n, ast.FunctionDef) and n.name == 'level_card_statuses')
    query = ast.get_source_segment(source, fn)
    assert not gate.scan(query, 'backend/services/cards.py')
    assert gate.scan(strip_tenant(query), 'backend/services/cards.py')
    assert gate.scan(query.replace('(user_id, book_id,', '(book_id, book_id,'), 'backend/services/cards.py')


def test_literal_schema_proof_is_reported():
    root = path.parents[1]
    evidence = []
    assert not gate.scan((root / 'backend/data/db.py').read_text(), 'backend/data/db.py', evidence)
    assert any('FRESH_SCHEMA literal parsed' in line for line in evidence)
    assert any('models.SCHEMA literal parsed' in line for line in evidence)
