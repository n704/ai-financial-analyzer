"""Shared test setup: no network, no leaked background state.

`quotes.fetch_quotes` schedules metadata lookups on a background pool. Left
alone in a test run that would make real yfinance calls off the request path,
and a thread finishing after another test cleared the caches would pollute it —
which showed up as `test_a_symbol_is_only_warmed_once_while_in_flight` passing
alone and failing in the full suite.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import market_data, quotes  # noqa: E402


def _no_network_meta(ticker, symbol):
    raise AssertionError(
        f"A test tried to fetch metadata for {symbol} over the network. "
        "Patch `market_data._download_meta` or `quotes.warm_meta` in the test."
    )


@pytest.fixture(autouse=True)
def _isolate_market_data(monkeypatch):
    """Reset caches and background state around every test."""
    monkeypatch.setattr(market_data, "_download_meta", _no_network_meta)
    market_data.clear_caches()
    quotes.clear_cache()
    quotes._warming.clear()
    yield
    market_data.clear_caches()
    quotes.clear_cache()
    quotes._warming.clear()
