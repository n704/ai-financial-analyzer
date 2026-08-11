"""Background metadata warm-up: names fill in without blocking the response."""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import market_data, quotes  # noqa: E402


@pytest.fixture(autouse=True)
def _settle_background():
    """Let any pool work finish before the next test resets shared state."""
    yield
    _settle(lambda: not quotes._warming)


def _frame(symbol="AAPL"):
    idx = pd.date_range("2026-08-05", periods=2, freq="B", tz="America/New_York")
    cols = pd.MultiIndex.from_tuples([(symbol, "Close")])
    return pd.DataFrame([[100.0], [110.0]], index=idx, columns=cols)


def _settle(predicate, timeout=2.0):
    """Wait for the background pool without sleeping longer than needed."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_the_first_response_does_not_wait_for_metadata(monkeypatch):
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: _frame())
    monkeypatch.setattr(quotes, "warm_meta", lambda s: {"name": "Apple Inc."})

    (quote,) = quotes.fetch_quotes(["AAPL"])
    # Served from the cold cache: the ticker stands in for the name.
    assert quote["name"] == "AAPL"


def test_metadata_is_warmed_in_the_background(monkeypatch):
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: _frame())
    monkeypatch.setattr(
        market_data, "_download_meta", lambda ticker, s: {"name": "Apple Inc.", "currency": "USD"}
    )

    quotes.fetch_quotes(["AAPL"])
    assert _settle(lambda: market_data.cached_meta("AAPL") is not None)

    quotes.clear_cache()
    (quote,) = quotes.fetch_quotes(["AAPL"])
    assert quote["name"] == "Apple Inc."
    assert quote["currency"] == "USD"


def test_a_symbol_is_only_warmed_once_while_in_flight(monkeypatch):
    # A symbol used by no other test, so a stray background thread elsewhere
    # cannot warm it first and make this look like a pass with zero calls.
    symbol = "WARMONCE"
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: _frame(symbol))
    calls = []

    def slow_warm(s):
        calls.append(s)
        time.sleep(0.05)
        return {"name": "Warm Once Inc."}

    monkeypatch.setattr(quotes, "warm_meta", slow_warm)

    for _ in range(5):
        quotes.clear_cache()
        quotes.fetch_quotes([symbol])
    assert _settle(lambda: not quotes._warming)
    assert len(calls) == 1


def test_a_failing_warm_up_never_reaches_the_caller(monkeypatch):
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: _frame())

    def boom(symbol):
        raise RuntimeError("yahoo said no")

    monkeypatch.setattr(quotes, "warm_meta", boom)

    (quote,) = quotes.fetch_quotes(["AAPL"])
    assert quote["price"] == 110.0
    # The symbol is released so a later request can retry.
    assert _settle(lambda: not quotes._warming)


def test_an_already_cached_symbol_is_not_refetched(monkeypatch):
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: _frame())
    market_data._meta_cache.set("AAPL", {"name": "Apple Inc."})

    def explode(symbol):
        raise AssertionError("should not refetch a cached symbol")

    monkeypatch.setattr(quotes, "warm_meta", explode)
    (quote,) = quotes.fetch_quotes(["AAPL"])
    assert quote["name"] == "Apple Inc."
