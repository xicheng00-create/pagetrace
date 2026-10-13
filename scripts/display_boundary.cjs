// Node 自带 Acorn：不引入页面依赖，用真正 ESTree 遍历及别名污点传播。
const {parse} = require('internal/deps/acorn/acorn/dist/acorn');
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const tree = parse(input.source, {ecmaVersion: 'latest'});
const raw = new Set(['subtitle','title','text','answer','back','book','chapter','concept']);
const aliases = new Set();
const bad = new Set();
function rawInput(n) {
  if (!n) return false;
  if (n.type === 'Identifier') return aliases.has(n.name);
  if (n.type === 'MemberExpression' && raw.has(prop(n))) return true;
  if (n.type === 'CallExpression' && (n.callee.name === 'esc' || n.callee.type === 'MemberExpression' && prop(n.callee) === 'esc')) {
    return n.arguments.some(v => v.type === 'MemberExpression' && ['book','chapter','back'].includes(prop(v)));
  }
  return children(n).some(rawInput);
}
function children(n) {return Object.values(n).flatMap(v => Array.isArray(v) ? v : [v]).filter(v => v && typeof v.type === 'string');}
function constant(n) {
  if (!n) return null;
  if (n.type === 'Literal') return n.value;
  if (n.type === 'ArrayExpression') return n.elements.map(constant);
  if (n.type === 'BinaryExpression' && n.operator === '+') return constant(n.left) + constant(n.right);
  if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression' && prop(n.callee) === 'join') {
    const v = constant(n.callee.object); return Array.isArray(v) ? v.join(constant(n.arguments[0])) : null;
  }
  return null;
}
function prop(n) {return n.computed ? constant(n.property) : n.property.name;}
function tainted(n) {
  if (!n) return false;
  if (n.type === 'Identifier') return aliases.has(n.name);
  if (n.type === 'MemberExpression' && raw.has(prop(n))) return true;
  if (n.type === 'CallExpression' && (n.callee.name === 'esc' || n.callee.type === 'MemberExpression' && prop(n.callee) === 'esc')) return false;
  if (n.type === 'ConditionalExpression') return tainted(n.consequent) || tainted(n.alternate);
  return children(n).some(tainted);
}
function walk(n, scope='<module>') {
  if (/Function/.test(n.type)) scope = n.id?.name || scope;
  if (n.type === 'VariableDeclarator' && n.id.type === 'ObjectPattern') {
    for (const p of n.id.properties) {
      if (raw.has(p.key?.name || p.key?.value) && p.value.type === 'Identifier') aliases.add(p.value.name);
    }
  }
  if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && tainted(n.init)) aliases.add(n.id.name);
  if (n.type === 'AssignmentExpression' && n.left.type === 'Identifier' && tainted(n.right)) aliases.add(n.left.name);
  if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression') {
    const name = prop(n.callee);
    if (name === 'join' && tainted(n.callee.object)) bad.add('raw display join: ' + input.source.slice(n.start,n.end));
    if (['split','slice','substring','substr','match','matchAll','replace','trim'].includes(name) && tainted(n.callee.object)) bad.add('raw display field derivation');
    if (name === 'exec' && n.arguments.some(tainted)) bad.add('regex display field derivation');
    if (n.callee.object.name === 'Math' && !(input.allow || []).includes(scope)) bad.add('Math outside whitelist: ' + scope);
  }
  if ((n.type === 'BinaryExpression' && n.operator === '+' || n.type === 'TemplateLiteral') && rawInput(n)) {
    // HTML 模板只承载转义后的完整字段；裸原文插值拼接禁止。
    const pieces = n.type === 'TemplateLiteral' ? n.expressions : [n.left,n.right];
    if (pieces.some(v => tainted(v) && v.type !== 'CallExpression') || pieces.filter(v => v.type === 'CallExpression' && rawInput(v) && (v.callee.name === 'esc' || v.callee.type === 'MemberExpression' && prop(v.callee) === 'esc')).length > 1) bad.add('raw display concatenation: ' + input.source.slice(n.start,n.end));
  }
  children(n).forEach(v => walk(v, scope));
}
for(let i=0;i<3;i++) walk(tree);
console.log(JSON.stringify([...bad]));
