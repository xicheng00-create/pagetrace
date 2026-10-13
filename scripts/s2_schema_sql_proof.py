"""Statically evaluate the bounded schema builder, without importing application code."""
import ast
import re
import sqlite3
from pathlib import Path


def ddl_only(sql):
    """Check every complete statement, never just the first keyword."""
    sql = re.sub(r'--[^\n]*|/\*.*?\*/', '', sql, flags=re.S)
    statement = ''
    for char in sql:
        statement += char
        if char == ';' and sqlite3.complete_statement(statement):
            if not re.match(r'\s*(?:CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\b|ALTER\s+TABLE\b|PRAGMA\b)', statement, re.I):
                return False
            # Schema definitions may contain ON DELETE, but never embedded queries.
            if re.search(r'\b(?:SELECT|INSERT|UPDATE|ATTACH|DROP)\b', statement, re.I):
                return False
            statement = ''
    return not statement.strip()


def schema_sql(root, fresh=False):
    relative = 'backend/data/s2_schema.py' if fresh else 'backend/data/models.py'
    name = 'FRESH_SCHEMA' if fresh else 'SCHEMA'
    tree = ast.parse((root / relative).read_text())
    assignments = [n.value for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    if len(assignments) != 1:
        raise ValueError('schema must have exactly one literal definition')
    node = assignments[0]
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        raise ValueError('schema must be a literal string')
    return node.value


def resolve_schema(node, filename):
    if filename != 'backend/data/db.py':
        return None
    root = Path(__file__).resolve().parents[1]
    if isinstance(node, ast.Attribute) and ast.unparse(node) == 'models.SCHEMA':
        return schema_sql(root)
    if isinstance(node, ast.Name) and node.id == 'FRESH_SCHEMA':
        return schema_sql(root, fresh=True)
    return None
