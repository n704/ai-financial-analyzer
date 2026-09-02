"""Fixture ``MarketDataProvider`` (P6.2): deterministic synthetic bars, no
network. Serves CI, the ``test``/``offline`` profiles, and the forecast eval.

Two modes: hand ``series`` (per-ticker bars) for exact assertions, or let it
synthesize a seeded geometric random walk per ticker — the same ticker and
seed always yield the same bars, on weekdays only. ``known_tickers`` limits the
symbols it will serve so the ``TickerNotFound`` path can be exercised.
"""

from __future__ import annotations

import datetime as dt
import random
from collections.abc import Collection, Mapping, Sequence

from app.providers.base import Bar, MarketDataUnavailable, PriceSeries, TickerNotFound

_SUPPORTED_INTERVAL = "1d"


class FixtureMarketDataProvider:
    def __init__(
        self,
        *,
        seed: int = 0,
        series: Mapping[str, Sequence[Bar]] | None = None,
        known_tickers: Collection[str] | None = None,
        daily_drift: float = 0.0002,
        daily_volatility: float = 0.015,
    ) -> None:
        self._seed = seed
        self._series = {k.upper(): tuple(v) for k, v in (series or {}).items()}
        self._known = {t.upper() for t in known_tickers} if known_tickers is not None else None
        self._drift = daily_drift
        self._vol = daily_volatility

    @property
    def provider(self) -> str:
        return "fixture"

    @property
    def supports_intraday(self) -> bool:
        return False

    def fetch_series(self, ticker: str, start: dt.date, end: dt.date, interval: str) -> PriceSeries:
        if interval != _SUPPORTED_INTERVAL:
            raise MarketDataUnavailable(
                f"fixture market data serves {_SUPPORTED_INTERVAL!r} bars only, not {interval!r}"
            )
        if start > end:
            raise MarketDataUnavailable(f"start {start} is after end {end}")
        symbol = ticker.upper()
        if self._known is not None and symbol not in self._known:
            raise TickerNotFound(symbol, source=self.provider)

        scripted = self._series.get(symbol)
        bars = (
            tuple(b for b in scripted if start <= b.date <= end)
            if scripted is not None
            else self._synthesize(symbol, start, end)
        )
        if not bars:
            raise TickerNotFound(symbol, source=self.provider)
        return PriceSeries(
            ticker=symbol, interval=interval, source=self.provider, as_of=end, bars=bars
        )

    def _synthesize(self, symbol: str, start: dt.date, end: dt.date) -> tuple[Bar, ...]:
        rng = random.Random(f"{self._seed}:{symbol}")
        close = 20.0 + rng.uniform(0.0, 380.0)
        bars: list[Bar] = []
        day = start
        while day <= end:
            if day.weekday() < 5:
                open_ = close
                close = close * pow(2.718281828459045, rng.gauss(self._drift, self._vol))
                wiggle = abs(rng.gauss(0.0, self._vol / 2)) * close
                bars.append(
                    Bar(
                        date=day,
                        open=round(open_, 4),
                        high=round(max(open_, close) + wiggle, 4),
                        low=round(max(0.01, min(open_, close) - wiggle), 4),
                        close=round(close, 4),
                        volume=float(rng.randint(200_000, 5_000_000)),
                    )
                )
            day += dt.timedelta(days=1)
        return tuple(bars)


__all__ = ["FixtureMarketDataProvider"]
