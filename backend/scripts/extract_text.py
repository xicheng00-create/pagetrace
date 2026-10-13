"""独立抽文：python backend/scripts/extract_text.py PDF --root /tmp/uploads。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.upload import extract_text  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf')
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    print(json.dumps(extract_text(args.pdf, args.root), ensure_ascii=False))


if __name__ == '__main__':
    main()
