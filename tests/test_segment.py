import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from services.segment import segment_book, segment_text


def test_segment_deterministic(tmp_path):
    path = tmp_path / 'raw.md'
    path.write_text('<!-- p.1 -->\n\n第1章\n\n' + ('完整段落。' * 100 + '\n\n') * 5)
    a = segment_book(path, 'hash')
    mtime = path.with_name('blocks.json').stat().st_mtime_ns
    assert segment_book(path, 'hash') == a
    assert path.with_name('blocks.json').stat().st_mtime_ns == mtime
    assert len(a['blocks']) > 1


def test_no_cross_chapter_block():
    blocks = segment_text('第1章\n\n甲。\n\n第2章\n\n乙。', 'hash')
    assert [(b['chapter'], b['text']) for b in blocks] == [('第1章', '甲。'), ('第2章', '乙。')]
    assert all(1 <= len(b['text']) <= 2000 for b in blocks)
    assert segment_text('普通段落。', 'hash')[0]['chapter'] == '全文'
    assert segment_text('第1章', 'hash') == []
    assert segment_text('', 'hash') == []
    from services.segment import SegmentationError
    with pytest.raises(SegmentationError, match='人工分段'):
        segment_text('长' * 2001, 'hash')


def test_segment_cli(tmp_path, monkeypatch, capsys):
    from scripts.segment_book import main
    path = tmp_path / 'raw.md'
    path.write_text('第1章\n\n完整段落。')
    monkeypatch.setattr(sys, 'argv', ['segment_book', str(path), '--book-hash', 'hash'])
    main()
    assert 'sha256' in capsys.readouterr().out
