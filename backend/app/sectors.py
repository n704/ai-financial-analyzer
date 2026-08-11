"""Compare a stock against its sector, using the matched SPDR sector ETF.

yfinance reports a sector string per symbol; each maps to one of the eleven
State Street sector ETFs, which are liquid, long-lived and free to fetch. That
is a proxy, not the sector itself — an equal-weight peer basket would weight
differently — but it needs no maintained peer list and no extra data source.

Symbols with no usable sector (crypto, many ADRs, ETFs themselves) fall back to
the broad market and say so, rather than being labelled with a sector they do
not belong to.
"""
from __future__ import annotations

import math

from . import comparison
from .market_data import MarketDataError, cached_meta, warm_meta

MARKET_ETF = "SPY"

# yfinance's sector vocabulary -> State Street sector SPDR.
SECTOR_ETF: dict[str, str] = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}

ETF_NAMES: dict[str, str] = {
    "XLK": "Technology Select Sector SPDR",
    "XLF": "Financial Select Sector SPDR",
    "XLV": "Health Care Select Sector SPDR",
    "XLY": "Consumer Discretionary Select Sector SPDR",
    "XLP": "Consumer Staples Select Sector SPDR",
    "XLE": "Energy Select Sector SPDR",
    "XLI": "Industrial Select Sector SPDR",
    "XLB": "Materials Select Sector SPDR",
    "XLRE": "Real Estate Select Sector SPDR",
    "XLU": "Utilities Select Sector SPDR",
    "XLC": "Communication Services Select Sector SPDR",
    MARKET_ETF: "SPDR S&P 500 ETF",
}


def resolve_sector(symbol: str) -> tuple[str | None, str | None]:
    """(sector, etf) for `symbol`. Either may be None when unknown.

    Reads the metadata cache first and only pays for a lookup on a miss, since
    `ticker.info` is yfinance's slowest endpoint.
    """
    symbol = symbol.strip().upper()
    if symbol in ETF_NAMES:
        # The sector ETF has no sector of its own; comparing it to itself would
        # produce a flat line and a beta of exactly 1.
        return None, None
    meta = cached_meta(symbol)
    if meta is None:
        try:
            meta = warm_meta(symbol)
        except Exception:  # noqa: BLE001 - fall back to the broad market
            meta = {}
    sector = meta.get("sector") or None
    return sector, SECTOR_ETF.get(sector) if sector else None


def sector_comparison(symbol: str, interval: str = "1d", bars: int = 180) -> dict:
    """Stock against its sector ETF and the broad market."""
    symbol = symbol.strip().upper()
    if not symbol:
        raise MarketDataError("Symbol is required.")

    sector, etf = resolve_sector(symbol)
    caveat = None
    if etf is None:
        caveat = (
            f"No sector could be resolved for {symbol}"
            + (f" (Yahoo reports '{sector}', which has no matching sector ETF)" if sector else "")
            + f", so it is compared against the broad market ({MARKET_ETF}) only."
        )

    # The benchmark must lead the list: `compare_symbols` measures beta and
    # correlation against its first symbol, so putting the stock first would
    # give it a beta of 1.00 against itself.
    wanted = etf or MARKET_ETF
    ordered = list(dict.fromkeys([wanted, symbol, MARKET_ETF]))
    result = comparison.compare_symbols(ordered, interval, bars)

    rows = {r["symbol"]: r for r in result["symbols"]}
    if symbol not in rows:
        raise MarketDataError(
            f"{symbol} does not share enough history with {wanted} to compare."
        )

    # Trust the comparison's own benchmark: if the ETF failed to resolve or was
    # dropped for insufficient overlap, it fell back to the next surviving
    # column, and quoting a beta against a symbol that is not there would lie.
    benchmark = result["benchmark"]
    if benchmark == symbol:
        benchmark = None
        caveat = (
            caveat
            or f"No benchmark shared enough history with {symbol}, so only its own series is shown."
        )
    elif etf and benchmark != etf:
        caveat = caveat or (
            f"{etf} did not share enough history with {symbol}, so {benchmark} is used instead."
        )

    stock = rows[symbol]
    relative = _relative(stock, rows.get(benchmark)) if benchmark else {}

    return {
        "symbol": symbol,
        "name": stock["name"],
        "sector": sector,
        "sector_etf": etf,
        "sector_etf_name": ETF_NAMES.get(etf) if etf else None,
        "market_etf": MARKET_ETF if MARKET_ETF in rows else None,
        "benchmark": benchmark,
        "caveat": caveat,
        "interval": result["interval"],
        "interval_label": result["interval_label"],
        "bars": result["bars"],
        "start": result["start"],
        "end": result["end"],
        "symbols": result["symbols"],
        "relative": relative,
        "relative_strength": _relative_strength(stock, rows.get(benchmark)) if benchmark else [],
        "unavailable": result["unavailable"],
    }


def _relative(stock: dict, bench: dict | None) -> dict:
    """How the stock did against its benchmark, and how much of that is beta."""
    if not bench:
        return {}
    s, b = stock["metrics"], bench["metrics"]
    stock_ret, bench_ret = s["total_return_pct"], b["total_return_pct"]
    beta = s["beta_vs_benchmark"]

    excess = None if stock_ret is None or bench_ret is None else stock_ret - bench_ret
    alpha = _alpha(stock_ret, bench_ret, beta)
    return {
        "benchmark": bench["symbol"],
        "stock_return_pct": stock_ret,
        "benchmark_return_pct": bench_ret,
        "excess_return_pct": comparison._f(excess),
        "alpha_pct": comparison._f(alpha),
        "beta": beta,
        "correlation": s["correlation_vs_benchmark"],
        "stock_vol_pct": s["annualized_vol_pct"],
        "benchmark_vol_pct": b["annualized_vol_pct"],
    }


def _alpha(stock_ret_pct: float | None, bench_ret_pct: float | None, beta: float | None):
    """Return left over after removing the part beta explains.

    Computed in log space, because beta is measured on log returns: doubling a
    log return does not double the simple return, so mixing the two makes a
    stock that tracked its sector exactly — pure leverage, zero skill — appear
    to have tens of percent of alpha.
    """
    if stock_ret_pct is None or bench_ret_pct is None or beta is None:
        return None
    s, b = stock_ret_pct / 100, bench_ret_pct / 100
    if s <= -1 or b <= -1:  # a total wipeout has no logarithm
        return None
    return comparison._f((math.exp(math.log1p(s) - beta * math.log1p(b)) - 1) * 100)


def _relative_strength(stock: dict, bench: dict | None) -> list[dict]:
    """Stock ÷ benchmark, rebased to 100 — rising means outperforming.

    Both series are already rebased to the same first bar, so the ratio starts
    at 100 by construction and its slope is pure relative performance.
    """
    if not bench:
        return []
    out = []
    for a, b in zip(stock["series"], bench["series"]):
        if not b["value"]:
            continue
        out.append({"time": a["time"], "value": comparison._f(a["value"] / b["value"] * 100)})
    return out


def explain_sector(result: dict) -> list[dict]:
    """Plain-English reading of the sector comparison."""
    rel = result.get("relative") or {}
    if not rel:
        return []

    symbol = result["symbol"]
    bench = rel["benchmark"]
    bench_label = (
        f"its sector ({result['sector']}, tracked by {bench})"
        if bench == result.get("sector_etf")
        else f"the broad market ({bench})"
    )
    label = result["interval_label"].lower()

    out = [
        {
            "title": "What is being compared",
            "body": (
                f"{symbol} is shown against {bench_label} over {result['bars']} shared {label} "
                "bars, every line rebased to 100 at the start so only relative performance is "
                "visible. A sector ETF is a proxy for the sector, not the sector itself — it is "
                "cap-weighted, so a handful of large members drive most of its move."
            ),
        }
    ]

    excess = rel.get("excess_return_pct")
    if excess is not None:
        verb = "outperformed" if excess >= 0 else "underperformed"
        out.append(
            {
                "title": f"{symbol} {verb} by {abs(excess):.2f} points",
                "body": (
                    f"{symbol} returned {rel['stock_return_pct']:+.2f}% over the window against "
                    f"{rel['benchmark_return_pct']:+.2f}% for {bench}. The relative-strength line "
                    "is the ratio of the two: rising means the stock is gaining on its benchmark, "
                    "falling means it is losing ground, and flat means it is simply riding it."
                ),
            }
        )

    beta, alpha = rel.get("beta"), rel.get("alpha_pct")
    if beta is not None:
        if beta > 1.2:
            sensitivity = (
                f"amplifies {bench}: a 1% move there has tended to mean a {beta:.2f}% move here, "
                "in both directions"
            )
        elif beta < 0.8:
            sensitivity = (
                f"damps {bench}: a 1% move there has tended to mean only a {beta:.2f}% move here"
            )
        else:
            sensitivity = f"tracks {bench} closely, moving about {beta:.2f}% for each 1% there"
        body = f"Beta of {beta:.2f} means {symbol} {sensitivity}. "
        if alpha is not None:
            body += (
                f"Alpha of {alpha:+.2f}% is what is left after subtracting the part explained by "
                "that sensitivity — beating a rising sector while being twice as sensitive to it "
                "is leverage, not skill. Over one window and with no risk-free rate subtracted, "
                "treat this as descriptive rather than a measure of manager quality."
            )
        out.append({"title": "How much is just the sector moving", "body": body})

    corr = rel.get("correlation")
    if corr is not None:
        reading = (
            "almost all of its movement is sector movement, so holding it instead of the ETF "
            "concentrates risk without diversifying it"
            if corr > 0.8
            else "it moves largely on its own news rather than with its sector"
            if corr < 0.4
            else "it moves with its sector about as much as it moves on its own"
        )
        out.append(
            {
                "title": "How closely it follows the sector",
                "body": (
                    f"Correlation with {bench} is {corr:.2f} over this window — {reading}. "
                    f"{symbol} was {'more' if (rel.get('stock_vol_pct') or 0) > (rel.get('benchmark_vol_pct') or 0) else 'less'} "
                    f"volatile than {bench} ({rel.get('stock_vol_pct'):.1f}% against "
                    f"{rel.get('benchmark_vol_pct'):.1f}% annualised)."
                ),
            }
        )

    if result.get("caveat"):
        out.append({"title": "Why there is no sector here", "body": result["caveat"]})

    return out
