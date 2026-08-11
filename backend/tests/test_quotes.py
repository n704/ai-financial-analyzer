"""Batched quote snapshots. No network: `yf.download` is monkeypatched."""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import market_data, quotes  # noqa: E402
from backend.app.market_data import MarketDataError  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    quotes.clear_cache()
    market_data.clear_caches()
    yield
    quotes.clear_cache()
    market_data.clear_caches()


def _index(n=3):
    return pd.date_range("2026-08-05", periods=n, freq="B", tz="America/New_York")


def multi_frame(data: dict[str, list[float]]):
    """Mimic yfinance's (ticker, field) column MultiIndex for several tickers."""
    idx = _index(len(next(iter(data.values()))))
    columns, values = [], []
    for symbol, closes in data.items():
        for field in ("Open", "High", "Low", "Close", "Volume"):
            columns.append((symbol, field))
            values.append(closes if field == "Close" else [1.0] * len(closes))
    return pd.DataFrame(
        dict(zip(columns, values)), index=idx, columns=pd.MultiIndex.from_tuples(columns)
    )


def flat_frame(closes: list[float]):
    """Single-ticker downloads come back with plain columns."""
    idx = _index(len(closes))
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1.0] * len(closes)},
        index=idx,
    )


# ---------------------------------------------------------- symbol parsing


def test_parse_symbols_normalises_dedupes_and_preserves_order():
    assert quotes.parse_symbols(" aapl, msft ,,AAPL\nnvda") == ["AAPL", "MSFT", "NVDA"]


def test_parse_symbols_handles_nothing():
    assert quotes.parse_symbols(None) == []
    assert quotes.parse_symbols("  ,  ") == []


def test_parse_symbols_rejects_an_unreasonable_batch():
    with pytest.raises(MarketDataError, match="limit"):
        quotes.parse_symbols(",".join(f"S{i}" for i in range(quotes.MAX_SYMBOLS + 1)))


# ------------------------------------------------------------------ quotes


def test_quotes_report_price_and_change(monkeypatch):
    monkeypatch.setattr(
        quotes.yf, "download", lambda **kw: multi_frame({"AAPL": [100.0, 110.0], "MSFT": [50.0, 45.0]})
    )
    out = {q["symbol"]: q for q in quotes.fetch_quotes(["AAPL", "MSFT"])}
    assert out["AAPL"]["price"] == 110.0
    assert out["AAPL"]["change_pct"] == pytest.approx(10.0)
    assert out["MSFT"]["change_pct"] == pytest.approx(-10.0)
    assert out["AAPL"]["error"] is None


def test_a_single_symbol_download_is_read_correctly(monkeypatch):
    """yfinance returns flat columns for one ticker and a MultiIndex for many."""
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: flat_frame([100.0, 101.0]))
    (quote,) = quotes.fetch_quotes(["AAPL"])
    assert quote["price"] == 101.0


def test_a_symbol_with_no_data_is_reported_not_dropped(monkeypatch):
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: multi_frame({"AAPL": [100.0, 110.0]}))
    out = {q["symbol"]: q for q in quotes.fetch_quotes(["AAPL", "NOSUCH"])}
    assert set(out) == {"AAPL", "NOSUCH"}
    assert out["NOSUCH"]["price"] is None
    assert out["NOSUCH"]["error"]


def test_an_entirely_empty_download_does_not_raise(monkeypatch):
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: pd.DataFrame())
    out = quotes.fetch_quotes(["AAPL"])
    assert out[0]["price"] is None


def test_a_single_bar_leaves_change_undefined(monkeypatch):
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: multi_frame({"AAPL": [100.0]}))
    (quote,) = quotes.fetch_quotes(["AAPL"])
    assert quote["price"] == 100.0
    assert quote["change_pct"] is None


def test_results_keep_the_requested_order(monkeypatch):
    monkeypatch.setattr(
        quotes.yf,
        "download",
        lambda **kw: multi_frame({"AAPL": [1.0, 2.0], "MSFT": [1.0, 2.0], "NVDA": [1.0, 2.0]}),
    )
    assert [q["symbol"] for q in quotes.fetch_quotes(["NVDA", "AAPL", "MSFT"])] == [
        "NVDA",
        "AAPL",
        "MSFT",
    ]


def test_no_symbols_means_no_download(monkeypatch):
    def explode(**kw):
        raise AssertionError("should not download")

    monkeypatch.setattr(quotes.yf, "download", explode)
    assert quotes.fetch_quotes([]) == []


def test_a_repeat_request_is_served_from_cache(monkeypatch):
    calls = []

    def download(**kw):
        calls.append(1)
        return multi_frame({"AAPL": [100.0, 110.0]})

    monkeypatch.setattr(quotes.yf, "download", download)
    quotes.fetch_quotes(["AAPL"])
    quotes.fetch_quotes(["AAPL"])
    assert len(calls) == 1


def test_names_come_from_the_metadata_cache_when_warm(monkeypatch):
    """A watchlist must not trigger `ticker.info` per row, so names fill in
    only once some other request has warmed the cache."""
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: multi_frame({"AAPL": [1.0, 2.0]}))

    (cold,) = quotes.fetch_quotes(["AAPL"])
    assert cold["name"] == "AAPL"

    market_data._meta_cache.set("AAPL", {"name": "Apple Inc.", "currency": "USD"})
    quotes.clear_cache()
    (warm,) = quotes.fetch_quotes(["AAPL"])
    assert warm["name"] == "Apple Inc."
    assert warm["currency"] == "USD"
