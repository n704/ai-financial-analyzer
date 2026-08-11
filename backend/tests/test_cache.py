"""TTL cache behaviour and its wiring into market-data fetches. No network."""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import market_data  # noqa: E402
from backend.app.cache import TTLCache  # noqa: E402


class FakeClock:
    """Monotonic clock the test drives by hand, so nothing sleeps."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# ------------------------------------------------------------------- TTLCache


def test_hit_within_ttl_does_not_call_the_factory_again():
    clock = FakeClock()
    cache = TTLCache(ttl=60, clock=clock)
    calls = []

    def factory():
        calls.append(1)
        return "value"

    assert cache.get_or_set("k", factory) == "value"
    clock.advance(59)
    assert cache.get_or_set("k", factory) == "value"
    assert len(calls) == 1


def test_entry_expires_after_the_ttl():
    clock = FakeClock()
    cache = TTLCache(ttl=60, clock=clock)
    calls = []

    cache.get_or_set("k", lambda: calls.append(1) or "a")
    clock.advance(61)
    cache.get_or_set("k", lambda: calls.append(1) or "a")
    assert len(calls) == 2
    assert cache.get("k") is not None


def test_distinct_keys_do_not_collide():
    cache = TTLCache(ttl=60)
    cache.set(("AAPL", "1d", 128), "apple")
    cache.set(("AAPL", "1d", 256), "apple-long")
    cache.set(("MSFT", "1d", 128), "microsoft")
    assert cache.get(("AAPL", "1d", 128)) == "apple"
    assert cache.get(("AAPL", "1d", 256)) == "apple-long"
    assert cache.get(("MSFT", "1d", 128)) == "microsoft"


def test_per_entry_ttl_overrides_the_default():
    clock = FakeClock()
    cache = TTLCache(ttl=300, clock=clock)
    cache.set("short", "v", ttl=60)
    cache.set("long", "v")
    clock.advance(61)
    assert cache.get("short") is None
    assert cache.get("long") == "v"


def test_eviction_keeps_the_cache_bounded():
    cache = TTLCache(ttl=600, max_entries=3)
    for i in range(10):
        cache.set(f"k{i}", i)
    assert len(cache._entries) <= 3
    # The most recent write always survives.
    assert cache.get("k9") == 9


def test_clear_drops_everything():
    cache = TTLCache(ttl=600)
    cache.set("k", "v")
    cache.clear()
    assert cache.get("k") is None


# --------------------------------------------------------- market_data wiring


def _frame(n=40):
    idx = pd.date_range("2026-01-01", periods=n, freq="B", tz="America/New_York")
    values = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values, "volume": [1e6] * n},
        index=idx,
    )


@pytest.fixture(autouse=True)
def _clean_caches():
    market_data.clear_caches()
    yield
    market_data.clear_caches()


def test_fetch_ohlcv_serves_a_second_identical_request_from_cache(monkeypatch):
    calls = []

    def fake_download(symbol, interval, bars):
        calls.append((symbol, interval, bars))
        return market_data.MarketData(symbol, interval, _frame(), {"symbol": symbol})

    monkeypatch.setattr(market_data, "_download_ohlcv", fake_download)

    market_data.fetch_ohlcv("AAPL", "1d", 128)
    market_data.fetch_ohlcv("aapl", "1d", 128)  # same key after normalisation
    assert calls == [("AAPL", "1d", 128)]


def test_fetch_ohlcv_refetches_for_a_different_bar_count(monkeypatch):
    calls = []
    monkeypatch.setattr(
        market_data,
        "_download_ohlcv",
        lambda s, i, b: calls.append(b)
        or market_data.MarketData(s, i, _frame(), {"symbol": s}),
    )
    market_data.fetch_ohlcv("AAPL", "1d", 128)
    market_data.fetch_ohlcv("AAPL", "1d", 260)
    assert calls == [128, 260]


def test_cached_frame_is_copied_so_callers_cannot_poison_it(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_download_ohlcv",
        lambda s, i, b: market_data.MarketData(s, i, _frame(), {"symbol": s}),
    )
    first = market_data.fetch_ohlcv("AAPL", "1d", 128)
    first.df.loc[first.df.index[0], "close"] = -999.0
    first.meta["name"] = "mutated"

    second = market_data.fetch_ohlcv("AAPL", "1d", 128)
    assert second.df["close"].iloc[0] == 100.0
    assert "name" not in second.meta


def test_failed_downloads_are_not_cached(monkeypatch):
    calls = []

    def boom(symbol, interval, bars):
        calls.append(1)
        raise market_data.MarketDataError("no data")

    monkeypatch.setattr(market_data, "_download_ohlcv", boom)
    for _ in range(2):
        with pytest.raises(market_data.MarketDataError):
            market_data.fetch_ohlcv("NOPE", "1d", 128)
    assert len(calls) == 2


def test_intraday_uses_the_shorter_ttl(monkeypatch):
    """A 15m bar must not be served from a 5-minute-old cache entry."""
    recorded = {}

    def capture(key, factory, ttl=None):
        recorded["ttl"] = ttl
        return market_data.MarketData("AAPL", "15m", _frame(), {})

    monkeypatch.setattr(market_data._ohlcv_cache, "get_or_set", capture)

    market_data.fetch_ohlcv("AAPL", "15m", 128)
    assert recorded["ttl"] == market_data.config.OHLCV_CACHE_TTL_INTRADAY

    market_data.fetch_ohlcv("AAPL", "1d", 128)
    assert recorded["ttl"] == market_data.config.OHLCV_CACHE_TTL_DAILY
