"""Price-series cache repository (P6.2) — **the one repository deliberately
not user-scoped** (ARCHITECTURE.md §5).

Closing prices are public and identical for every tenant, so the cache is
keyed by ``(ticker, interval, source, as_of)`` alone and shared across users;
nothing user-identifying is stored here. Every *forecast* built from these
bars is a ``user_id``-owned row in ``forecasts`` (``ForecastRepository``),
where the ownership check lives. This class does not extend
``ScopedRepository`` so the absence of a ``user_id`` filter reads as
intentional rather than as an omission.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import PriceSeriesCache
from app.providers.base import Bar, PriceSeries


def _bars_to_json(bars: tuple[Bar, ...]) -> list[dict[str, object]]:
    return [
        {
            "d": bar.date.isoformat(),
            "o": bar.open,
            "h": bar.high,
            "l": bar.low,
            "c": bar.close,
            "v": bar.volume,
        }
        for bar in bars
    ]


def _bars_from_json(rows: list[dict[str, object]]) -> tuple[Bar, ...]:
    bars: list[Bar] = []
    for row in rows:
        volume = row.get("v")
        bars.append(
            Bar(
                date=dt.date.fromisoformat(str(row["d"])),
                open=float(str(row["o"])),
                high=float(str(row["h"])),
                low=float(str(row["l"])),
                close=float(str(row["c"])),
                volume=float(str(volume)) if volume is not None else None,
            )
        )
    return tuple(bars)


def to_price_series(row: PriceSeriesCache) -> PriceSeries:
    return PriceSeries(
        ticker=row.ticker,
        interval=row.interval,
        source=row.source,
        as_of=row.as_of,
        bars=_bars_from_json(row.bars),
    )


class PriceSeriesRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, *, ticker: str, interval: str, source: str, as_of: dt.date
    ) -> PriceSeriesCache | None:
        stmt = select(PriceSeriesCache).where(
            PriceSeriesCache.ticker == ticker,
            PriceSeriesCache.interval == interval,
            PriceSeriesCache.source == source,
            PriceSeriesCache.as_of == as_of,
        )
        return self.session.scalar(stmt)

    def put(self, series: PriceSeries) -> PriceSeriesCache:
        """Insert or replace the cached bars for the series' key."""
        row = self.get(
            ticker=series.ticker,
            interval=series.interval,
            source=series.source,
            as_of=series.as_of,
        )
        if row is None:
            row = PriceSeriesCache(
                ticker=series.ticker,
                interval=series.interval,
                source=series.source,
                as_of=series.as_of,
            )
            self.session.add(row)
        row.start_date = series.start
        row.end_date = series.end
        row.bars = _bars_to_json(series.bars)
        row.fetched_at = utcnow()
        self.session.flush()
        return row

    def purge_fetched_before(self, cutoff: dt.datetime) -> int:
        """TTL eviction (ARCHITECTURE.md §5, "Forecast delete / account
        delete": the cache is evicted by TTL, never by user)."""
        stale = list(
            self.session.scalars(
                select(PriceSeriesCache).where(PriceSeriesCache.fetched_at < cutoff)
            )
        )
        for row in stale:
            self.session.delete(row)
        self.session.flush()
        return len(stale)


__all__ = ["PriceSeriesRepository", "to_price_series"]
