"""HOME-001 每日格言：按日轮转、当天固定、跨日 +1、不编造作者、空表回落。

反向断言：数据源是纯字符串列表（无 author 字段，故不可能运行期拼接署名）。
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from services import quotes  # noqa: E402
from services.clock import TZ8  # noqa: E402


def test_source_enough_and_no_author():
    assert len(quotes.QUOTES) >= 40, "格言 ≥40 句"
    for q in quotes.QUOTES:
        assert isinstance(q, str) and q.strip()
    # 反向断言：每条都是纯字符串 —— 没有 author / 出处字段（绝不编造署名）
    assert all(not isinstance(q, (tuple, dict, list)) for q in quotes.QUOTES)


def test_same_day_fixed_next_day_plus_one():
    d = date(2026, 9, 27)
    a, b = quotes.quote_for(d), quotes.quote_for(d)
    assert a["id"] == b["id"], "同一天两次取 → 同 ID"     # 当天固定
    nxt = quotes.quote_for(d + timedelta(days=1))
    assert nxt["id"] == (a["id"] + 1) % len(quotes.QUOTES)  # 跨日 +1（模句数）


def test_epoch_day_is_zero():
    assert quotes.quote_for(quotes.QUOTE_EPOCH)["id"] == 0


def test_wraps_around_full_cycle():
    n = len(quotes.QUOTES)
    d = quotes.QUOTE_EPOCH + timedelta(days=n)
    assert quotes.quote_for(d)["id"] == 0                  # 走满一周期回到起点


def test_empty_source_falls_back_not_blank():
    r = quotes.quote_for(date(2026, 9, 27), quotes=[])
    assert r["id"] is None and r["text"] == "今日复习" and r["total"] == 0


def test_zero_size_no_divide_by_zero():
    assert quotes.quote_index(date(2026, 9, 27), 0) == 0   # 不除零


def test_today_quote_uses_local_day():
    """同一本地日（跨 UTC 边界）恒定；跨本地午夜 +1。"""
    a = quotes.today_quote(at=datetime(2026, 9, 27, 0, 1, tzinfo=TZ8))
    b = quotes.today_quote(at=datetime(2026, 9, 27, 23, 59, tzinfo=TZ8))
    assert a["id"] == b["id"]
    c = quotes.today_quote(at=datetime(2026, 9, 28, 0, 1, tzinfo=TZ8))
    assert c["id"] == (a["id"] + 1) % len(quotes.QUOTES)


def test_api_endpoint(tmp_path, monkeypatch):
    from app import create_app
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "q.sqlite3"))
    app = create_app("development")
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/quote")
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert set(d) == {"id", "text", "total"}     # 反向断言：无 author 字段
        assert d["total"] == len(quotes.QUOTES)
        assert d["text"] in quotes.QUOTES
