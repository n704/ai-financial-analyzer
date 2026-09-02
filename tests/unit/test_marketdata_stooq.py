"""P6.2: the stooq adapter's vendor specifics — symbol mapping, CSV parsing,
"No data" → ``TickerNotFound``, and 5xx/429 backoff — against a mocked HTTP
transport (the live path is the contract suite behind ``LIVE_MARKET_DATA=1``)."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from app.providers.base import MarketDataUnavailable, TickerNotFound
from app.providers.marketdata.stooq import (
    StooqMarketDataProvider,
    parse_stooq_csv,
    to_stooq_symbol,
)

CSV = """Date,Open,High,Low,Close,Volume
2026-03-03,101,103,100,102,1500
2026-03-02,100,102,99,101,1000
2026-03-04,102,104,101,103,
"""


def test_symbol_mapping() -> None:
    assert to_stooq_symbol("AAPL") == "aapl.us"
    assert to_stooq_symbol("BRK.B") == "brk-b.us"
    assert to_stooq_symbol("aapl.us") == "aapl.us"
    assert to_stooq_symbol("VOD", suffix=".uk") == "vod.uk"


def test_parse_sorts_and_handles_missing_volume() -> None:
    bars = parse_stooq_csv(CSV, ticker="X", source="stooq")
    assert [b.date.isoformat() for b in bars] == ["2026-03-02", "2026-03-03", "2026-03-04"]
    assert bars[-1].volume is None
    assert bars[0].close == 101.0


def test_parse_no_data_and_garbage() -> None:
    with pytest.raises(TickerNotFound):
        parse_stooq_csv("No data", ticker="X", source="stooq")
    with pytest.raises(MarketDataUnavailable):
        parse_stooq_csv("<html>oops</html>", ticker="X", source="stooq")
    with pytest.raises(MarketDataUnavailable):
        parse_stooq_csv("Date,Open,High,Low,Close\nnot-a-date,1,2,3,4\n", ticker="X", source="s")


def _provider(handler: httpx.MockTransport) -> StooqMarketDataProvider:
    return StooqMarketDataProvider(
        client=httpx.Client(transport=handler), sleep=lambda _s: None, max_retries=2
    )


def test_fetch_series_end_to_end_with_mocked_http() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=CSV)

    series = _provider(httpx.MockTransport(handler)).fetch_series(
        "brk.b", dt.date(2026, 3, 1), dt.date(2026, 3, 3), "1d"
    )
    assert seen[0].url.params["s"] == "brk-b.us"
    assert seen[0].url.params["i"] == "d"
    assert series.ticker == "BRK.B"
    assert [b.date.day for b in series.bars] == [2, 3]  # the 4th is outside [start, end]
    assert series.as_of == dt.date(2026, 3, 3)


def test_transient_errors_are_retried_then_surfaced() -> None:
    attempts = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503) if attempts["n"] == 1 else httpx.Response(200, text=CSV)

    series = _provider(httpx.MockTransport(flaky)).fetch_series(
        "AAPL", dt.date(2026, 3, 1), dt.date(2026, 3, 5), "1d"
    )
    assert attempts["n"] == 2 and len(series) == 3

    def always_down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    with pytest.raises(MarketDataUnavailable):
        _provider(httpx.MockTransport(always_down)).fetch_series(
            "AAPL", dt.date(2026, 3, 1), dt.date(2026, 3, 5), "1d"
        )

    def not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(MarketDataUnavailable):
        _provider(httpx.MockTransport(not_found)).fetch_series(
            "AAPL", dt.date(2026, 3, 1), dt.date(2026, 3, 5), "1d"
        )


def test_unsupported_interval() -> None:
    with pytest.raises(MarketDataUnavailable):
        _provider(httpx.MockTransport(lambda r: httpx.Response(200))).fetch_series(
            "AAPL", dt.date(2026, 3, 1), dt.date(2026, 3, 5), "5m"
        )
