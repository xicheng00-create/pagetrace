"""只在段落之间分块；超长原段拒绝而不句中切（UP-003）。"""
import hashlib
import json
import re
from pathlib import Path

ANCHOR = re.compile(r'^(?:第[\d一二三四五六七八九十百零〇]+章|第?[\d一二三四五六七八九十百零〇]+[卷部])[^\n]*$')


class SegmentationError(Exception):
    """Input text cannot be split into valid upload blocks."""


def segment_text(text, book_hash):
    chapter, pending, blocks = '全文', [], []

    def flush():
        if pending:
            body = '\n\n'.join(pending)
            blocks.append({'book_hash': book_hash, 'chapter': chapter,
                           'idx': len(blocks), 'text': body,
                           'text_sha256': hashlib.sha256(body.encode()).hexdigest()})
            pending.clear()

    # 页标记不是正文段落，不能打断章节归属。
    text = re.sub(r'<!-- p\.\d+ -->', '', text)
    paragraphs = re.split(r'\n\s*\n', text.strip())
    for paragraph in paragraphs:
        # PDF 文本常把章题与首段连在一起，独立章题行也须识别。
        for piece in re.split(r'(?m)^(?=(?:第[\d一二三四五六七八九十百零〇]+章|第?[\d一二三四五六七八九十百零〇]+[卷部]))', paragraph):
            piece = piece.strip()
            if not piece:
                continue
            lines = piece.split('\n', 1)
            if ANCHOR.fullmatch(lines[0]):
                flush()
                chapter = lines[0]
                piece = lines[1].strip() if len(lines) > 1 else ''
            if not piece:
                continue
            if len(piece) > 2000:
                raise SegmentationError('原文段落超过 2000 字，需人工分段；不会句中切块')
            if pending and len('\n\n'.join([*pending, piece])) > 1800:
                flush()
            pending.append(piece)
    flush()
    return blocks


def segment_book(raw_path, book_hash):
    blocks = segment_text(Path(raw_path).read_text(encoding='utf-8'), book_hash)
    target = Path(raw_path).with_name('blocks.json')
    content = json.dumps(blocks, ensure_ascii=False, sort_keys=True, indent=2)
    if not target.exists() or target.read_text(encoding='utf-8') != content:
        target.write_text(content, encoding='utf-8')
    return {'blocks': blocks, 'sha256': hashlib.sha256(content.encode()).hexdigest()}
