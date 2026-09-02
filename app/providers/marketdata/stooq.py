"""Stooq ``MarketDataProvider`` (P6.2): keyless end-of-day bars over a plain
CSV endpoint — the least-friction live source (SPEC.md open question #7).

Vendor specifics kept in here, per ARCHITECTURE.md §3: the symbol convention
(lower-case, US listings suffixed ``.us``, share-class dots written as dashes
— ``BRK.B`` → ``brk-b.us``), the CSV layout, "No data" as the not-found
signal, and backoff on transient HTTP failures. Stooq's daily closes are
split-adjusted; dividend adjustment is not guaranteed, which the ``source``
stamp on every series makes auditable.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import time
from collections.abc import Callable

import httpx

from app.providers.base import Bar, MarketDataUnavailable, PriceSeries, TickerNotFound
from app.providers.retry import with_backoff

STOOQ_URL = "https://stooq.com/q/d/l/"

_INTERVAL_CODES = {"1d": "d", "1wk": "w", "1mo": "m"}


def to_stooq_symbol(ticker: str, *, suffix: str = ".us") -> str:
    """``BRK.B`` → ``brk-b.us``. Tickers carrying an explicit exchange suffix
    that Stooq already understands are passed through unchanged only when they
    end in the configured suffix."""
    symbol = ticker.strip().lower()
    if suffix and symbol.endswith(suffix.lower()):
        return symbol
    return symbol.replace(".", "-") + suffix


class StooqMarketDataProvider:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_s: float = 15.0,
        symbol_suffix: str = ".us",
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)
        self._suffix = symbol_suffix
        self._max_retries = max_retries
        self._sleep = sleep

    @property
    def provider(self) -> str:
        return "stooq"

    @property
    def supports_intraday(self) -> bool:
        return False

    def fetch_series(self, ticker: str, start: dt.date, end: dt.date, interval: str) -> PriceSeries:
        code = _INTERVAL_CODES.get(interval)
        if code is None:
            raise MarketDataUnavailable(
                f"stooq serves {sorted(_INTERVAL_CODES)} bars, not {interval!r}"
            )
        if start > end:
            raise MarketDataUnavailable(f"start {start} is after end {end}")
        symbol = to_stooq_symbol(ticker, suffix=self._suffix)
        params = {
            "s": symbol,
            "i": code,
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
        }

        def call() -> str:
            response = self._client.get(STOOQ_URL, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                raise _Transient(response.status_code)
            if response.status_code != 200:
                raise MarketDataUnavailable(
                    f"stooq returned HTTP {response.status_code} for {symbol!r}"
                )
            return response.text

        try:
            body = with_backoff(
                call,
                is_retryable=_retry_hint,
                max_retries=self._max_retries,
                base_delay=1.0,
                sleep=self._sleep,
            )
        except _Transient as exc:
            raise MarketDataUnavailable(
                f"stooq unavailable for {symbol!r} (HTTP {exc.status})"
            ) from exc
        except httpx.HTTPError as exc:
            raise MarketDataUnavailable(f"stooq request failed for {symbol!r}: {exc}") from exc

        bars = parse_stooq_csv(body, ticker=ticker.upper(), source=self.provider)
        bars = tuple(b for b in bars if start <= b.date <= end)
        if not bars:
            raise TickerNotFound(ticker.upper(), source=self.provider)
        return PriceSeries(
            ticker=ticker.upper(), interval=interval, source=self.provider, as_of=end, bars=bars
        )


class _Transient(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def _retry_hint(exc: Exception) -> float | None:
    if isinstance(exc, _Transient | httpx.TimeoutException | httpx.TransportError):
        return 0.0
    return None


def parse_stooq_csv(body: str, *, ticker: str, source: str) -> tuple[Bar, ...]:
    """``Date,Open,High,Low,Close,Volume`` rows → ascending :class:`Bar` tuple.
    Stooq answers an unknown symbol with a bare ``No data`` body."""
    text = body.strip()
    if not text or text.lower().startswith("no data"):
        raise TickerNotFound(ticker, source=source)
    reader = csv.DictReader(io.StringIO(text))
    required = {"Date", "Open", "High", "Low", "Close"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise MarketDataUnavailable(
            f"unexpected stooq CSV header {reader.fieldnames!r} for {ticker!r}"
        )
    bars: list[Bar] = []
    for row in reader:
        try:
            volume_raw = row.get("Volume")
            bars.append(
                Bar(
                    date=dt.date.fromisoformat(row["Date"]),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(volume_raw) if volume_raw not in (None, "") else None,
                )
            )
        except (KeyError, ValueError) as exc:
            raise MarketDataUnavailable(
                f"malformed stooq row for {ticker!r}: {row!r} ({exc})"
            ) from exc
    bars.sort(key=lambda b: b.date)
    deduped: list[Bar] = []
    for bar in bars:
        if deduped and deduped[-1].date == bar.date:
            deduped[-1] = bar
        else:
            deduped.append(bar)
    return tuple(deduped)


__all__ = ["STOOQ_URL", "StooqMarketDataProvider", "parse_stooq_csv", "to_stooq_symbol"]
