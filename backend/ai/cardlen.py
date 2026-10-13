"""UP-014 唯一机械切分：原文标点分片，连续贪心装箱；命名优先取调用者提供值，缺失走确定性兜底。"""
import json
import re

CAP = 222
BREAK = re.compile(r'(?<=[。！？；，、])')


def split_long(text):
    if len(text) <= CAP:
        return [text]
    parts = [p for p in BREAK.split(text) if p]
    if any(len(p) > CAP for p in parts):
        raise ValueError('要点无可用标点切分，需人工处理')
    out, current = [], ''
    for part in parts:
        if current and len(current) + len(part) > CAP:
            out.append(current)
            current = part
        else:
            current += part
    if current:
        out.append(current)
    if len(out) > 1 and len(out[-1]) < CAP // 3:
        previous = [p for p in BREAK.split(out[-2]) if p]
        if len(previous) > 1:
            move = previous[-1]
            if len(out[-2]) - len(move) >= len(move) and len(move) + len(out[-1]) <= CAP:
                out[-2], out[-1] = ''.join(previous[:-1]), move + out[-1]
    return out


def groups(row):
    packed, current, size = [], [], 0
    for point in row['answer_points']:
        for fragment in split_long(point):
            if current and size + len(fragment) > CAP:
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


def split_row(row, names=None):
    if sum(map(len, row['answer_points'])) <= CAP:
        return [row]
    packed = groups(row)
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


def split_line(line, names=None):
    row = json.loads(line)
    if sum(map(len, row['answer_points'])) <= CAP:
        return [line]
    return [json.dumps(r, ensure_ascii=False, separators=(',', ':'))
            for r in split_row(row, names)]
