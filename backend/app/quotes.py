"""Lightweight price snapshots for watchlist rows — no model involved.

A watchlist of 20 symbols must not cost 20 Kronos forecasts, or even 20
`Ticker.history` round-trips. This fetches every symbol in one batched
`yf.download` and reports last price, change since the previous close, and the
name from cached metadata.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import yfinance as yf

from . import config
from .cache import TTLCache
from .market_data import MarketDataError, cached_meta, warm_meta

logger = logging.getLogger(__name__)

MAX_SYMBOLS = 50

# Names and currencies come from yfinance's slow `ticker.info`, far too slow to
# block a watchlist render on. Instead the response goes out with whatever is
# cached and a few workers fetch the rest in the background, so the next poll
# (60s later) has them and the hour-long metadata cache keeps them.
WARM_WORKERS = 4
_warm_pool = ThreadPoolExecutor(max_workers=WARM_WORKERS, thread_name_prefix="meta-warm")
_warming: set[str] = set()
_warming_lock = threading.Lock()

# Quotes are the most-refreshed thing in the app, so they get their own short
# TTL keyed on the whole symbol set.
_quote_cache: TTLCache = TTLCache(ttl=config.OHLCV_CACHE_TTL_INTRADAY, max_entries=64)


def clear_cache() -> None:
    _quote_cache.clear()


def parse_symbols(raw: str | None) -> list[str]:
    """'aapl, msft,,AAPL' -> ['AAPL', 'MSFT'] — deduped, order preserved."""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        symbol = part.strip().upper()
        if symbol and symbol not in out:
            out.append(symbol)
    if len(out) > MAX_SYMBOLS:
        raise MarketDataError(f"Too many symbols ({len(out)}); the limit is {MAX_SYMBOLS}.")
    return out


def _closes_for(frame: pd.DataFrame, symbol: str, multi: bool) -> pd.Series | None:
    """Pull one symbol's close series out of a yfinance download.

    yfinance returns a flat frame for a single ticker and a column
    MultiIndex for several, and the level order depends on `group_by`.
    """
    try:
        if not multi:
            series = frame["Close"]
        elif (symbol, "Close") in frame.columns:
            series = frame[(symbol, "Close")]
        elif ("Close", symbol) in frame.columns:
            series = frame[("Close", symbol)]
        else:
            return None
    except (KeyError, TypeError):
        return None
    series = series.dropna()
    return series if not series.empty else None


def _download(symbols: list[str]) -> dict[str, dict]:
    """One batched request for every symbol. Missing symbols come back absent."""
    frame = yf.download(
        tickers=" ".join(symbols),
        period="7d",
        interval="1d",
        auto_adjust=True,
        actions=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if frame is None or frame.empty:
        return {}

    multi = isinstance(frame.columns, pd.MultiIndex)
    out: dict[str, dict] = {}
    for symbol in symbols:
        closes = _closes_for(frame, symbol, multi)
        if closes is None:
            continue
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else None
        out[symbol] = {
            "price": last,
            "previous_close": prev,
            "change_pct": (last / prev - 1) * 100 if prev else None,
            "as_of": closes.index[-1].isoformat(),
        }
    return out


def _describe(symbol: str) -> dict:
    """Name and currency from the shared metadata cache, if it is warm."""
    meta = cached_meta(symbol) or {}
    return {
        "name": meta.get("name") or symbol,
        "currency": meta.get("currency"),
        "sector": meta.get("sector"),
    }


def _warm(symbol: str) -> None:
    """Populate the metadata cache off the request path. Never raises."""
    try:
        warm_meta(symbol)
    except Exception:  # noqa: BLE001 - a missing name must not surface anywhere
        logger.debug("Metadata warm-up failed for %s", symbol, exc_info=True)
    finally:
        with _warming_lock:
            _warming.discard(symbol)


def _schedule_warm(symbols: list[str]) -> None:
    """Queue uncached symbols for background metadata lookup, once each."""
    with _warming_lock:
        pending = [s for s in symbols if cached_meta(s) is None and s not in _warming]
        _warming.update(pending)
    for symbol in pending:
        _warm_pool.submit(_warm, symbol)


def fetch_quotes(symbols: list[str]) -> list[dict]:
    """Snapshot every symbol. Unresolvable ones come back with `price: None`."""
    if not symbols:
        return []

    prices = _quote_cache.get_or_set(tuple(symbols), lambda: _download(symbols))
    _schedule_warm(symbols)

    quotes = []
    for symbol in symbols:
        price = prices.get(symbol)
        quotes.append(
            {
                "symbol": symbol,
                **_describe(symbol),
                "price": None,
                "previous_close": None,
                "change_pct": None,
                "as_of": None,
                "error": None if price else "No recent price data.",
                **(price or {}),
            }
        )
    return quotes
