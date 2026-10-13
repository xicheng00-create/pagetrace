"""UP-014 唯一机械切分：原文标点分片，连续贪心装箱；命名优先取调用者提供值，缺失走确定性兜底。

**本文件是切卡的唯一规范实现（owner 2026-10-13 拍板方案 A）。**
KB 侧 `scripts/card_split_2026-09-30/cardlen.py` 与 app 侧 `backend/ai/cardlen.py`
必须是**同一份文件**（sha256 相等），由 `check_cardlen_sync.py` 断言；两侧共用
`test_cardlen_vectors.py` 的测试向量。禁止任何一侧各改一套。

2026-10-13 修根因（owner 报「卡面语义截断 / 缺主语 / 开头是符号」，全库 13.8% 中招）：

  · 旧口径 = `BREAK=(?<=[。！？；，、])` 直接切 —— 不看括号/引号配平，
    于是 `伴侣互动模式（沟通技能低下，Simpson & Doss et al.，2007；…）` 被从括号内切开，
    下一张卡以 `Simpson & Doss et al.，2007；` 开头（缺主语、以文献开头）；
    引号内的「？」也被当句末，产生 `」），非常灵活…` 这类残片。
  · 新口径 = **切点必须落在配对括号/引号之外**，且按三级优先级：
    ① 句末 `。！？…` → ② `；` → ③ `，、：`（仅在前两级切不动时才用）。
    仍然切不动（括号内无标点）→ **原样放行**（宁可这张卡长，不可让人读不通）。
"""
import json
import re

CAP = 222

_OPEN = "（(「『【《[“‘"
_CLOSE = "）)」』】》]”’"
# 三级切点，优先级从高到低
_LEVELS = ("。！？…", "；", "，、:：")


def cut_points(text, levels):
    """返回允许作为切点的位置集合（切点在标点之后）。只有括号/引号外（深度 0）才算。"""
    depth = 0
    points = set()
    for i, ch in enumerate(text):
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        elif depth == 0 and any(ch in level for level in levels):
            points.add(i + 1)
    return points


def _atoms(text, levels):
    """按给定级别的切点把 text 切成原子片段（无损：拼接回去 == text）。"""
    points = sorted(cut_points(text, levels))
    out, prev = [], 0
    for p in points:
        if p > prev:
            out.append(text[prev:p])
            prev = p
    if prev < len(text):
        out.append(text[prev:])
    return out or [text]


def _pack(atoms, cap):
    """连续贪心装箱（不跨段重排、不改写、不新增、不丢字）。"""
    out, current = [], ""
    for atom in atoms:
        if current and len(current) + len(atom) > cap:
            out.append(current)
            current = atom
        else:
            current += atom
    if current:
        out.append(current)
    return out


def _tidy_tail(out, cap):
    """末段过短时，把前一段的最后一片挪过去（不拆句，只搬整片）。"""
    if len(out) > 1 and len(out[-1]) < cap // 3:
        previous = _atoms(out[-2], _LEVELS)
        if len(previous) > 1:
            move = previous[-1]
            if len(out[-2]) - len(move) >= len(move) and len(move) + len(out[-1]) <= cap:
                out[-2], out[-1] = "".join(previous[:-1]), move + out[-1]
    return out


def split_sentences(text, marks="。！？"):
    """按配平切句（切点在标点之后；括号/引号内不切）。无损，保留标点在句尾。

    export_cards.py 的要点抽取与卡片切分共用这一套切点判定 —— 上游断句与下游切分
    不一致，会把同一句话在两处各切一次，产生读不通的残片（2026-10-13 修）。

    默认 marks 只有句末标点：**分号不再断句**。旧口径按 `。；！？` 拆，把一句话
    拆成「以分号结尾的前半 + 下半」两条要点，装箱后两条落到不同卡 → 读者读到
    「卡末停在半句、下一张接着」；实测这一条贡献了绝大部分缺陷（5.6% → 1.6%）。
    """
    return [atom.strip() for atom in _atoms(text, (marks,)) if atom.strip()]


def split_long(text, cap=CAP):
    """把单条正文切成 ≤cap 的片段（无损、按优先级、括号外才切）。"""
    if len(text) <= cap:
        return [text]
    out = _pack(_atoms(text, _LEVELS[:1]), cap)
    for level in _LEVELS[1:]:
        if all(len(piece) <= cap for piece in out):
            break
        out = _pack([atom for piece in out for atom in _atoms(piece, (level,))], cap)
    # 括号/引号内无可用标点 → 原样放行，绝不硬切（旧实现在这里按 cap 硬切 = 造残句）
    return _tidy_tail(out, cap)


def groups(row, cap=CAP):
    """把整行的要点按顺序装箱成若干卡（每卡背面 ≤cap）。"""
    packed, current, size = [], [], 0
    for point in row['answer_points']:
        for fragment in split_long(point, cap):
            if current and size + len(fragment) > cap:
                packed.append(current)
                current, size = [], 0
            current.append(fragment)
            size += len(fragment)
    if current:
        packed.append(current)
    return packed


def derived_names(row, packed):
    """命名兜底（2026-10-11 真跑实测：模型可不给 subcards，命名缺失不得阻塞机械切分）。"""
    heads = []
    for points in packed:
        head = re.sub(r'[\s，。、；：！？·（）()\[\]【】]', '', points[0])[:8]
        heads.append(head or '要点')
    repeated = {h for h in heads if heads.count(h) > 1}
    names = []
    for index, head in enumerate(heads, 1):
        label = f'{head}{index}' if head in repeated else head
        question = f"{row['question']}（要点{index}）" if len(packed) > 1 else row['question']
        names.append({'name': label, 'question': question})
    return names


def split_row(row, names=None, cap=CAP):
    if sum(map(len, row['answer_points'])) <= cap:
        return [row]
    packed = groups(row, cap)
    fallback = derived_names(row, packed)
    result = []
    for index, points in enumerate(packed):
        name = names[index] if isinstance(names, list) and index < len(names) else None
        if not (isinstance(name, dict) and all(isinstance(name.get(k), str) and name[k].strip()
                                               for k in ('name', 'question'))):
            name = fallback[index]
        result.append({**row, 'title': row['title'] + ' · ' + name['name'],
                       'question': name['question'], 'answer_points': points})
    return result


def split_line(line, names=None, cap=CAP):
    row = json.loads(line)
    if sum(map(len, row['answer_points'])) <= cap:
        return [line]
    return [json.dumps(r, ensure_ascii=False, separators=(',', ':'))
            for r in split_row(row, names, cap)]


# ── 机械断言（两侧自检与导出契约共用，改口径必须同步这里）─────────────
_HEAD_BAD = re.compile(r'^\s*[」』）)\]】》”’。、；：！？…]')
_TAIL_BAD = ('；', '，', '、', '：', '（', '(', '——')


def unbalanced(text):
    """返回该条内不成对的配对标点列表（空 = 平衡）。"""
    bad = []
    for op, cl in (('（', '）'), ('「', '」'), ('《', '》'), ('【', '】'), ('(', ')'), ('[', ']'), ('“', '”')):
        if text.count(op) != text.count(cl):
            bad.append(op + cl)
    return bad


def card_defects(points):
    """一张卡的机械缺陷清单（导出前断言用）：首条残片 / 首条括号不平衡 / 末条未完。"""
    out = []
    if not points:
        return ['空卡']
    first = points[0].strip()
    if _HEAD_BAD.match(first):
        out.append('首条以标点开头')
    for i, p in enumerate(points):
        if unbalanced(p):
            out.append('第%d条括号/引号不平衡' % (i + 1))
    if points[-1].rstrip().endswith(_TAIL_BAD):
        out.append('末条停在半句（后半句在下一张卡）')
    return out
