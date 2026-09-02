"""P6.2 contract suite: every ``MarketDataProvider`` adapter satisfies the same
tests. ``fixture`` always runs (no network); ``stooq`` only when
``LIVE_MARKET_DATA=1`` — it makes real HTTP calls to a third party."""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable

import pytest

from app.providers.base import (
    MarketDataProvider,
    MarketDataUnavailable,
    PriceSeries,
    TickerNotFound,
)
from app.providers.marketdata.fixture import FixtureMarketDataProvider

_LIVE = os.environ.get("LIVE_MARKET_DATA") == "1"


def _build_stooq() -> MarketDataProvider:
    from app.providers.marketdata.stooq import StooqMarketDataProvider

    return StooqMarketDataProvider()


FACTORIES: dict[str, Callable[[], MarketDataProvider]] = {
    "fixture": lambda: FixtureMarketDataProvider(seed=1, known_tickers=["AAPL", "MSFT"]),
    "stooq": _build_stooq,
}
_PARAMS = [
    "fixture",
    pytest.param("stooq", marks=pytest.mark.skipif(not _LIVE, reason="LIVE_MARKET_DATA!=1")),
]


@pytest.fixture(params=_PARAMS)
def provider(request: pytest.FixtureRequest) -> MarketDataProvider:
    return FACTORIES[request.param]()


def test_satisfies_protocol(provider: MarketDataProvider) -> None:
    assert isinstance(provider, MarketDataProvider)
    assert provider.provider
    assert isinstance(provider.supports_intraday, bool)


def test_fetch_series_is_normalized(provider: MarketDataProvider) -> None:
    end = dt.date(2026, 6, 30)
    start = end - dt.timedelta(days=120)
    series = provider.fetch_series("aapl", start, end, "1d")
    assert isinstance(series, PriceSeries)
    assert series.ticker == "AAPL"
    assert series.interval == "1d"
    assert series.source == provider.provider
    assert series.as_of == end
    assert start <= series.start <= series.end <= end
    assert len(series) >= 40
    assert all(b.close > 0 and b.low <= b.close <= b.high for b in series.bars)
    assert series.dates == sorted(series.dates)


def test_unknown_ticker_is_not_found(provider: MarketDataProvider) -> None:
    with pytest.raises(TickerNotFound):
        provider.fetch_series("ZZZZQQQ", dt.date(2026, 1, 1), dt.date(2026, 3, 1), "1d")


def test_intraday_refused_when_unsupported(provider: MarketDataProvider) -> None:
    if provider.supports_intraday:
        pytest.skip("provider supports intraday")
    with pytest.raises(MarketDataUnavailable):
        provider.fetch_series("AAPL", dt.date(2026, 1, 1), dt.date(2026, 3, 1), "5m")
