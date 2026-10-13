#!/usr/bin/env python3
"""Conservative SQL scope gate: resolve literals, concatenations and local variables.

Unresolved runtime SQL in request/service code is a failure, not silent PASS.
Offline migration/import tools are separately listed, never whole-service allowlisted.
"""
import ast
import glob
import re
import sys

# Also support importlib-based regression loading from the repository root.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from s2_schema_sql_proof import ddl_only, resolve_schema

OWNED = {'books', 'upload_jobs', 'card_reviews', 'quiz_attempts', 'streak_days',
         'streak_freezes', 'reminder_log', 'prefs'}
OFFLINE = {
    'backend/data/models.py',
    'backend/scripts/migrate_status_reviewing.py',
    'backend/scripts/migrate_upload.py',
    'backend/scripts/ingest_store.py',
    'backend/scripts/ingest_kb.py',
    'backend/scripts/reswap_card_text.py',
    'backend/scripts/refresh_stale_quiz_items.py',
}
UNKNOWN = '__UNRESOLVED_SQL__'


def scan(source, filename, evidence=None):
    tree = ast.parse(source)
    symbols = {}
    expressions = {}
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    def text(node, depth=0):
        if depth > 15:
            return UNKNOWN
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return symbols.get(node.id, UNKNOWN)
        if isinstance(node, ast.JoinedStr):
            return ''.join(text(n.value, depth+1) if isinstance(n, ast.FormattedValue)
                           else text(n, depth+1) for n in node.values)
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
                and isinstance(node.left, ast.Constant) and node.left.value == '?'):
            return '?'
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return text(node.left, depth+1) + text(node.right, depth+1)
        if isinstance(node, ast.IfExp):
            return text(node.body, depth+1) + ' ' + text(node.orelse, depth+1)
        if isinstance(node, (ast.List, ast.Tuple)):
            return ' '.join(text(n, depth+1) for n in node.elts)
        if isinstance(node, ast.Dict):
            return ' '.join(text(n, depth+1) for n in node.values)
        if isinstance(node, ast.Subscript):
            return text(node.value, depth+1)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = text(node.func.value, depth+1)
            if node.func.attr == 'join' and node.args:
                sequence = node.args[0]
                if (isinstance(sequence, ast.GeneratorExp)
                        and isinstance(sequence.elt, ast.Constant)
                        and sequence.elt.value == '?'):
                    return '?'  # 可变长度占位符列，不是可变表名/SQL语法。
                return text(sequence, depth+1)
            if node.func.attr == 'replace' and len(node.args) >= 2:
                old, new = text(node.args[0], depth+1), text(node.args[1], depth+1)
                return base.replace(old, new)
            if node.func.attr in ('format', 'removeprefix'):
                return base
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = functions.get(node.func.id)
            if fn:
                return ' '.join(text(n.value, depth+1) for n in ast.walk(fn)
                                if isinstance(n, ast.Return) and n.value is not None)
        return UNKNOWN

    # Resolve local SQL names and tuple unpacking; keep unresolved markers visible.
    for _ in range(5):
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign):
                for target in n.targets:
                    if isinstance(target, ast.Name):
                        symbols[target.id] = text(n.value)
                        expressions[target.id] = n.value
                    elif isinstance(target, ast.Tuple):
                        for index, name in enumerate(target.elts):
                            if not isinstance(name, ast.Name):
                                continue
                            value = n.value
                            base = expressions.get(value.value.id) if (
                                isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name)) else None
                            if isinstance(base, ast.Dict) and all(isinstance(v, ast.Tuple) for v in base.values):
                                symbols[name.id] = ' '.join(text(v.elts[index]) for v in base.values)
                            else:
                                symbols[name.id] = text(value)
            if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
                symbols[n.target.id] = symbols.get(n.target.id, '') + text(n.value)
    bad = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ('execute', 'executemany', 'executescript') and n.args):
            continue
        sql = text(n.args[0])
        if filename in OFFLINE:
            continue
        try:
            schema = resolve_schema(n.args[0], filename)
        except (ValueError, KeyError, StopIteration, TypeError):
            schema = None
        if schema is not None:
            sql = schema
        if ddl_only(sql if sql.rstrip().endswith(';') else sql + ';'):
            if schema is not None and evidence is not None:
                evidence.append(f'G3 DDL PROOF {filename}:{n.lineno}: {ast.unparse(n.args[0])} literal parsed; every statement verified DDL')
            continue
        if schema is not None:
            bad.append((n.lineno, 'schema literal contains non-DDL statement', sql))
            continue
        if UNKNOWN in sql:
            bad.append((n.lineno, 'unresolved dynamic SQL requires binding proof', sql))
            continue
        if not re.search(r'\b(SELECT|UPDATE|DELETE|INSERT)\b', sql, re.I):
            continue
        if not any(re.search(r'\b' + table + r'\b', sql, re.I) for table in OWNED):
            continue
        # Merely mentioning owner_id in a SELECT is not an identity predicate.
        predicate = re.search(r'\b(?:\w+\.)?(?:user_id|owner_id)\s*=\s*\?', sql, re.I)
        insert = re.search(r'\bINSERT\b.+\b(?:user_id|owner_id)\b.+\bVALUES\b', sql, re.I | re.S)
        if not (predicate or insert):
            bad.append((n.lineno, 'missing bound tenant predicate', sql))
        elif len(n.args) < 2 or '?' not in sql:
            bad.append((n.lineno, 'tenant placeholder has no parameter argument', sql))
        elif predicate and isinstance(n.args[1], (ast.Tuple, ast.List)):
            # 对静态参数序列校验 tenant 对应槽位，不把「有参数」等同绑定身份。
            params = n.args[1].elts
            if not any(isinstance(value, ast.Starred) for value in params):
                slot = sql[:predicate.end()].count('?') - 1
                if slot >= len(params):
                    bad.append((n.lineno, 'tenant placeholder missing its parameter slot', sql))
                else:
                    identity = ast.unparse(params[slot])
                    if not re.search(r'\b(?:uid|user_id|owner_id|current_user_id|_uid)\b', identity):
                        bad.append((n.lineno, 'tenant slot is not a user identity expression: ' + identity, sql))
    return bad


def main():
    failures = []
    evidence = []
    for filename in sorted(glob.glob('backend/**/*.py', recursive=True)):
        try:
            failures.extend((filename, *item) for item in scan(open(filename).read(), filename, evidence))
        except SyntaxError as exc:
            failures.append((filename, exc.lineno, 'syntax error', str(exc)))
    for proof in evidence:
        print(proof)
    for filename, line, reason, sql in failures:
        print(f'G3 FAIL {filename}:{line}: {reason}: {" ".join(sql.split())}')
    if failures:
        print(f'G3 FAIL candidates={len(failures)} (no unresolved SQL is silently skipped)')
        return 1
    print('G3 PASS resolved SQL scope and parameter argument checks')
    return 0


if __name__ == '__main__':
    sys.exit(main())
