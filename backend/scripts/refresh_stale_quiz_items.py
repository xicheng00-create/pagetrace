"""一次性刷新既有脏题（QUIZ-011 + QUIZ-012）：卡文语种 ≠ 题面语种、或机械降级的选择题 → 同 id 覆盖重生。

口径（与断言同源）：
- 英文卡：题面不得含汉字（'一'..'鿿' 区段）。
- 中文卡：选项不得为 ["True","False"]（英文是非标签）。
- **QUIZ-012（新，2026-10-03）**：`source='fallback'` 的**选择题**一律视为脏题 —— 机械降级的选择题
  干扰项取自同章要点池，旧实现恒取池首两条（生产实测：全章干扰项恒为「了解（knowledge）」「关心（care）」），
  且这类题是「LLM 题型不符 → 整批降级」的残留；提示词修好后重生即可拿到真选择题。
覆盖只走 `quizgen.update_item`：保留 `id`，不删不插，`quiz_attempts` 外键与行数不动。

用法（默认生产库 data-local/review.sqlite3）：
    python3 scripts/refresh_stale_quiz_items.py          # dry-run，只打印待刷行
    python3 scripts/refresh_stale_quiz_items.py --apply  # 落地 + 断言 quiz_attempts 行数不变
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 与 `app.py` 同源加载 `settings.local`：不加载 → `DEEPSEEK_API_KEY` 为空 → 全部机械降级，刷新等于白刷
from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR.parent / "settings.local")

from services import language, quizgen  # noqa: E402

from scripts import ingest_store  # noqa: E402

logger = logging.getLogger(__name__)


def has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in (text or ""))


def is_stale(card: dict, stem: str, options: list[str]) -> bool:
    """卡文语种 != 题面语种 的判定（QUIZ-011）。"""
    if language.is_english_card(card):
        return has_cjk(stem)
    return list(options) == ["True", "False"]


def reason_of(card: dict, row) -> str | None:
    """脏题判据（QUIZ-011 语种 / QUIZ-012 机械选择题）；干净返回 None。"""
    if is_stale(card, row["stem"], json.loads(row["options"])):
        return "language"
    if row["type"] == "choice" and row["source"] == "fallback":
        return "fallback_choice"
    return None


def stale_rows(con) -> list:
    """扫描全部题目，返回脏题行（每行附 `reason` 列）。"""
    rows = con.execute(
        "SELECT qi.id, qi.card_id, qi.type, qi.stem, qi.options, qi.source,"
        " c.front, c.back, cp.chapter_id"
        " FROM quiz_items qi JOIN cards c ON c.id=qi.card_id"
        " JOIN concepts cp ON cp.id=c.concept_id"
    ).fetchall()
    out = []
    for r in rows:
        card = {
            "card_id": r["card_id"],
            "front": r["front"],
            "back": r["back"],
            "chapter_id": r["chapter_id"],
        }
        why = reason_of(card, r)
        if why:
            d = dict(r)
            d["reason"] = why
            out.append(d)
    return out


def _regenerate(con, row) -> dict:
    """按该卡当前卡文重生（LLM → 机械降级）；最终仍语种不符则强制机械派生。"""
    card = {
        "card_id": row["card_id"],
        "front": row["front"],
        "back": row["back"],
        "chapter_id": row["chapter_id"],
    }
    item = quizgen._produce(con, [card], [row["type"]])[row["card_id"]]
    if is_stale(card, item["stem"], item["options"]):
        item = quizgen.mechanical_item(con, card, row["type"])
    return item


def refresh(con, apply: bool = False) -> list:
    """刷新全部脏题；apply=False 仅返回待刷行，不改库。

    断言口径：`language` 类必须刷新到 0（确定性可达）；`fallback_choice` 依赖 LLM 可用性，
    残留只记 `logging.warning`（不许把它当作刷新失败），避免「LLM 不可用 → 脚本必崩」。
    """
    stale = stale_rows(con)
    if not apply:
        return stale
    before = con.execute("SELECT COUNT(*) FROM quiz_attempts WHERE user_id IS NOT NULL").fetchone()[0]
    for r in stale:
        item = _regenerate(con, r)
        quizgen.update_item(con, r["id"], r["card_id"], item)
    con.commit()
    after = con.execute("SELECT COUNT(*) FROM quiz_attempts WHERE user_id IS NOT NULL").fetchone()[0]
    assert after == before, f"quiz_attempts 行数漂移：{before} → {after}"
    remaining = stale_rows(con)
    still_lang = [r for r in remaining if r["reason"] == "language"]
    assert not still_lang, f"刷新后仍残留 {len(still_lang)} 条语种不一致题目"
    still_fb = [r for r in remaining if r["reason"] == "fallback_choice"]
    if still_fb:
        logger.warning(
            "刷新后仍有 %d 条机械降级选择题（LLM 不可用或题型再次不符）：%s",
            len(still_fb),
            [r["id"] for r in still_fb],
        )
    return stale


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="落地写库（默认 dry-run）")
    ap.add_argument("--db", default=os.environ.get("DATABASE_PATH"), help="SQLite 路径")
    ap.add_argument(
        "--allow-mechanical",
        action="store_true",
        help="允许在无 DEEPSEEK_API_KEY 时照样落地（结果只会是机械题）",
    )
    args = ap.parse_args()

    have_key = bool(os.environ.get("DEEPSEEK_API_KEY"))
    print(f"LLM 可用：{'是' if have_key else '否（无 DEEPSEEK_API_KEY → 只能机械派生）'}")
    if args.apply and not have_key and not args.allow_mechanical:
        print(
            "拒绝落地：无 DEEPSEEK_API_KEY 时刷新只会得到机械题（等于白刷）。补 key 或用 --allow-mechanical。"
        )
        return 2

    path = args.db or str(Path(BACKEND_DIR).parent / "data-local" / "review.sqlite3")
    con = ingest_store.connect(path)
    stale = refresh(con, apply=args.apply)
    if not stale:
        print("无脏题：全部题目卡文/题面语种一致。")
        return 0
    for r in stale:
        print(f"  id={r['id']} card={r['card_id']} type={r['type']} [{r['reason']}] stem={r['stem'][:48]!r}")
    n_lang = sum(1 for r in stale if r["reason"] == "language")
    n_fb = len(stale) - n_lang
    tail = (
        f"已刷新 {len(stale)} 条（语种 {n_lang} · 机械选择题 {n_fb}），quiz_attempts 行数不变。"
        if args.apply
        else f"待刷新 {len(stale)} 条（语种 {n_lang} · 机械选择题 {n_fb}）；dry-run 未改库"
    )
    print(tail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
