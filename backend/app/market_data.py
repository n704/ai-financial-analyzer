"""Market data access: fetch OHLCV history and build future bar timestamps."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import time as dtime

import pandas as pd
import yfinance as yf

from . import config
from .cache import TTLCache


class MarketDataError(RuntimeError):
    """Raised when a symbol cannot be resolved or has too little history."""


@dataclass(frozen=True)
class IntervalSpec:
    """How one bar interval behaves: yfinance limits and calendar semantics."""

    label: str
    intraday: bool
    #  yfinance refuses intraday requests beyond these windows.
    max_days: int | None
    # Approximate calendar days per bar, used to size the download window.
    days_per_bar: float
    # Bars per year, used to annualise volatility.
    bars_per_year: float


INTERVALS: dict[str, IntervalSpec] = {
    "1d": IntervalSpec("Daily", False, None, 1.45, 252),
    "1h": IntervalSpec("Hourly", True, 720, 0.22, 1638),
    "30m": IntervalSpec("30 minutes", True, 55, 0.11, 3276),
    "15m": IntervalSpec("15 minutes", True, 55, 0.055, 6552),
}

REQUIRED_COLS = ["open", "high", "low", "close", "volume"]

# Bars are cached for less than one bar's worth of time, so a cached response is
# never staler than the bar it describes. Metadata (name, sector, currency)
# barely changes and comes from yfinance's slowest endpoint, so it holds longer.
_ohlcv_cache: TTLCache = TTLCache(ttl=config.OHLCV_CACHE_TTL_DAILY, max_entries=256)
_meta_cache: TTLCache = TTLCache(ttl=config.META_CACHE_TTL, max_entries=512)


def clear_caches() -> None:
    """Drop every cached fetch. Used by tests and after config changes."""
    _ohlcv_cache.clear()
    _meta_cache.clear()


def cached_meta(symbol: str) -> dict | None:
    """Metadata for `symbol` if some earlier request already fetched it.

    Never triggers a download: callers that render many symbols at once (the
    watchlist) would otherwise pay for `ticker.info` per row.
    """
    return _meta_cache.get(symbol.strip().upper())


def warm_meta(symbol: str) -> dict:
    """Fetch and cache metadata for `symbol`. Slow — call off the request path."""
    symbol = symbol.strip().upper()
    return _safe_meta(yf.Ticker(symbol), symbol)


@dataclass
class MarketData:
    symbol: str
    interval: str
    df: pd.DataFrame  # columns: open, high, low, close, volume; DatetimeIndex
    meta: dict = field(default_factory=dict)


def _download_period(interval: str, bars: int) -> str:
    """Pick the smallest yfinance `period` that should cover `bars` bars."""
    spec = INTERVALS[interval]
    # Ask for ~60% more calendar span than strictly needed to absorb holidays.
    days = int(bars * spec.days_per_bar * 1.6) + 10
    if spec.max_days is not None:
        days = min(days, spec.max_days)
        return f"{days}d"
    if days > 3650:
        return "max"
    return f"{days}d"


def fetch_ohlcv(symbol: str, interval: str, bars: int) -> MarketData:
    """Download the most recent `bars` bars of OHLCV data for `symbol`.

    Results are cached briefly — see `_ohlcv_cache`. The returned frame is
    always a copy, so a caller that mutates it cannot poison the cache.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise MarketDataError("Symbol is required.")
    if interval not in INTERVALS:
        raise MarketDataError(f"Unsupported interval '{interval}'.")

    ttl = (
        config.OHLCV_CACHE_TTL_INTRADAY
        if INTERVALS[interval].intraday
        else config.OHLCV_CACHE_TTL_DAILY
    )
    md = _ohlcv_cache.get_or_set(
        (symbol, interval, bars), lambda: _download_ohlcv(symbol, interval, bars), ttl=ttl
    )
    return replace(md, df=md.df.copy(), meta=dict(md.meta))


def _download_ohlcv(symbol: str, interval: str, bars: int) -> MarketData:
    ticker = yf.Ticker(symbol)
    raw = ticker.history(
        period=_download_period(interval, bars),
        interval=interval,
        auto_adjust=True,
        actions=False,
    )
    if raw is None or raw.empty:
        raise MarketDataError(
            f"No market data returned for '{symbol}' at interval {interval}. "
            "Check the ticker symbol (Yahoo Finance format, e.g. AAPL, MSFT, BTC-USD, RELIANCE.NS)."
        )

    df = raw.rename(columns=str.lower)[REQUIRED_COLS].copy()
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0.0)
    # Kronos normalises per feature; a zero-variance volume column is harmless
    # but a zero-variance price column would blow up the inverse transform.
    if len(df) < 32:
        raise MarketDataError(
            f"Only {len(df)} usable bars for '{symbol}' at interval {interval}; need at least 32."
        )
    df = df.tail(bars)

    meta = _safe_meta(ticker, symbol)
    return MarketData(symbol=symbol, interval=interval, df=df, meta=meta)


def _safe_meta(ticker: "yf.Ticker", symbol: str) -> dict:
    """Best-effort descriptive metadata; never fatal to a forecast.

    `ticker.info` is yfinance's slowest endpoint and this is called once per
    symbol per comparison, so results are cached for an hour — company names
    and sectors do not move.
    """
    return dict(
        _meta_cache.get_or_set(symbol, lambda: _download_meta(ticker, symbol))
    )


def _download_meta(ticker: "yf.Ticker", symbol: str) -> dict:
    out = {"symbol": symbol, "name": symbol, "currency": None, "exchange": None, "sector": None}
    try:
        info = ticker.fast_info
        out["currency"] = getattr(info, "currency", None)
        out["exchange"] = getattr(info, "exchange", None)
    except Exception:
        pass
    try:
        # `get_info` is the slow path; tolerate rate limiting or schema drift.
        info = ticker.info or {}
        out["name"] = info.get("longName") or info.get("shortName") or symbol
        out["currency"] = out["currency"] or info.get("currency")
        out["exchange"] = out["exchange"] or info.get("fullExchangeName") or info.get("exchange")
        out["sector"] = info.get("sector")
    except Exception:
        pass
    return out


def _trades_weekends(index: pd.DatetimeIndex) -> bool:
    """True for 7-day markets (crypto, FX-ish) rather than exchange calendars."""
    weekend = sum(1 for ts in index if ts.weekday() >= 5)
    return weekend > 0.1 * len(index)


def _session_times(index: pd.DatetimeIndex, sessions: int = 5) -> list[dtime]:
    """Distinct intraday bar times observed in the most recent sessions."""
    recent_days = sorted({ts.date() for ts in index})[-sessions:]
    times = sorted({ts.time() for ts in index if ts.date() in recent_days})
    return times or [index[-1].time()]


def future_timestamps(index: pd.DatetimeIndex, interval: str, n: int) -> pd.DatetimeIndex:
    """Generate the next `n` bar timestamps after the end of `index`.

    Weekends are skipped for equity-style calendars; exchange holidays are not
    modelled, so far-out intraday stamps are approximate. Kronos only consumes
    the calendar features (minute/hour/weekday/day/month) of these stamps.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    last = index[-1]
    spec = INTERVALS[interval]

    if not spec.intraday:
        if _trades_weekends(index):
            # Crypto and other 7-day markets: every calendar day is a bar.
            return pd.date_range(start=last, periods=n + 1, freq="D", tz=index.tz)[1:]
        # Business days at the same time-of-day as the historical bars.
        return pd.bdate_range(start=last, periods=n + 1, tz=index.tz)[1:]

    times = _session_times(index)
    step = pd.Timedelta(minutes={"1h": 60, "30m": 30, "15m": 15}[interval])
    is_24x7 = len(times) >= (1440 // int(step.total_seconds() // 60)) - 1

    if is_24x7 or _trades_weekends(index):
        # Continuously traded market (e.g. crypto): a plain fixed-step grid.
        return pd.date_range(start=last + step, periods=n, freq=step, tz=index.tz)

    out: list[pd.Timestamp] = []
    day = last.normalize()
    # Resume in the current session after the last observed bar time.
    remaining = [t for t in times if t > last.time()]
    while len(out) < n:
        for t in remaining:
            out.append(day.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0))
            if len(out) == n:
                break
        day = (day + pd.Timedelta(days=1))
        while day.weekday() >= 5:  # skip Sat/Sun
            day += pd.Timedelta(days=1)
        remaining = times
    return pd.DatetimeIndex(out[:n], tz=index.tz)
