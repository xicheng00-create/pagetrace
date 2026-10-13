"""独立分段：python backend/scripts/segment_book.py RAW --book-hash SHA256。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.segment import segment_book  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw')
    parser.add_argument('--book-hash', required=True)
    args = parser.parse_args()
    print(json.dumps(segment_book(args.raw, args.book_hash), ensure_ascii=False))


if __name__ == '__main__':
    main()
