"""Side-by-side comparison of several symbols — price and risk, no model.

This is the fast half of the compare view: it returns in well under a second so
the screen is useful immediately. Kronos forecasts are opt-in and fetched one
symbol at a time, because `KronosEngine._infer_lock` serialises inference and a
batched request would just be a long silence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import analysis
from .market_data import INTERVALS, MarketDataError, fetch_ohlcv

MIN_SYMBOLS = 2
MAX_SYMBOLS = 6
# Below this many overlapping bars, correlation and beta are noise.
MIN_OVERLAP = 20


def _f(x) -> float | None:
    """JSON-safe float, matching `analysis._f`."""
    if x is None:
        return None
    x = float(x)
    return x if np.isfinite(x) else None


def _max_drawdown(closes: pd.Series) -> float:
    running_max = closes.cummax()
    return float((closes / running_max - 1.0).min())


def _beta(returns: pd.Series, benchmark: pd.Series) -> float | None:
    """Slope of `returns` regressed on `benchmark` — sensitivity, not fit."""
    variance = float(benchmark.var())
    if not np.isfinite(variance) or variance <= 1e-18:
        return None
    return float(returns.cov(benchmark) / variance)


def _correlation(returns: pd.Series, benchmark: pd.Series) -> float | None:
    """Pearson correlation, or None when either side never moves.

    A pegged or suspended symbol has zero variance, which makes correlation
    genuinely undefined; NumPy would divide by zero and warn about it.
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        return _f(returns.corr(benchmark))


def _comparable_index(index: pd.DatetimeIndex, intraday: bool) -> pd.DatetimeIndex:
    """Reduce timestamps to something two exchanges can be joined on.

    Daily bars are stamped at local midnight, so AAPL's 00:00 New York and
    BTC-USD's 00:00 UTC are the same trading day but different instants — an
    exact join finds zero overlap and silently drops one of them. Dropping the
    zone (rather than converting) keeps each bar on its own local calendar day,
    which is also right for Tokyo, where converting would shift the date back.

    Intraday is the opposite case: a 09:30 New York bar and a 14:30 UTC bar are
    genuinely the same moment, so those align on the instant.
    """
    if intraday:
        return index.tz_convert("UTC") if index.tz is not None else index
    naive = index.tz_localize(None) if index.tz is not None else index
    return naive.normalize()


def _align(
    frames: dict[str, pd.DataFrame], intraday: bool
) -> tuple[pd.DataFrame, list[str]]:
    """Inner-join close series on the bars every symbol actually traded.

    Symbols left with too little overlap are dropped and reported rather than
    quietly distorting the correlation matrix — one 24/7 symbol with a short
    history should not shrink an otherwise fine comparison to nothing.
    """
    series = {
        symbol: pd.Series(
            df["close"].to_numpy(), index=_comparable_index(df.index, intraday), name=symbol
        )
        # A symbol quoted twice in one bar (rare, but yfinance does it) would
        # make the join explode; keep the last.
        .pipe(lambda s: s[~s.index.duplicated(keep="last")])
        for symbol, df in frames.items()
    }

    dropped: list[str] = []
    remaining = dict(series)
    while True:
        closes = pd.DataFrame(remaining).dropna()
        if len(closes) >= MIN_OVERLAP or len(remaining) <= MIN_SYMBOLS:
            return closes, dropped
        # Drop whichever symbol is costing the most shared history.
        worst = max(
            remaining,
            key=lambda s: len(pd.DataFrame({k: v for k, v in remaining.items() if k != s}).dropna()),
        )
        dropped.append(worst)
        remaining.pop(worst)


def compare_symbols(symbols: list[str], interval: str = "1d", bars: int = 180) -> dict:
    """Rebased performance, risk metrics and correlations across `symbols`."""
    symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if len(symbols) < MIN_SYMBOLS:
        raise MarketDataError(f"Pick at least {MIN_SYMBOLS} symbols to compare.")
    if len(symbols) > MAX_SYMBOLS:
        raise MarketDataError(f"Too many symbols ({len(symbols)}); the limit is {MAX_SYMBOLS}.")
    spec = INTERVALS.get(interval)
    if spec is None:
        raise MarketDataError(f"Unsupported interval '{interval}'.")

    frames: dict[str, pd.DataFrame] = {}
    meta: dict[str, dict] = {}
    failed: dict[str, str] = {}
    for symbol in symbols:
        try:
            md = fetch_ohlcv(symbol, interval, bars)
        except MarketDataError as exc:
            # One dead ticker must not blank a four-symbol comparison.
            failed[symbol] = str(exc)
            continue
        frames[symbol] = md.df
        meta[symbol] = md.meta

    if len(frames) < MIN_SYMBOLS:
        detail = "; ".join(f"{s}: {e}" for s, e in failed.items())
        raise MarketDataError(f"Not enough symbols resolved to compare. {detail}")

    closes, dropped = _align(frames, spec.intraday)
    for symbol in dropped:
        failed[symbol] = f"Too few overlapping {spec.label.lower()} bars with the other symbols."
        frames.pop(symbol, None)
    if len(closes.columns) < MIN_SYMBOLS or len(closes) < MIN_OVERLAP:
        raise MarketDataError(
            "These symbols do not share enough history to compare "
            f"({len(closes)} overlapping {spec.label.lower()} bars). Try a longer window."
        )

    logret = np.log(closes / closes.shift(1)).dropna()
    benchmark = closes.columns[0]
    per_year = spec.bars_per_year

    out = []
    for symbol in closes.columns:
        series = closes[symbol]
        returns = logret[symbol]
        total = float(series.iloc[-1] / series.iloc[0] - 1) * 100
        vol = float(returns.std() * np.sqrt(per_year)) * 100 if len(returns) > 2 else None
        out.append(
            {
                "symbol": symbol,
                "name": meta.get(symbol, {}).get("name") or symbol,
                "currency": meta.get(symbol, {}).get("currency"),
                "sector": meta.get(symbol, {}).get("sector"),
                "last_close": _f(series.iloc[-1]),
                "metrics": {
                    "total_return_pct": _f(total),
                    "annualized_vol_pct": _f(vol),
                    "return_per_unit_risk": _f(total / vol) if vol else None,
                    "max_drawdown_pct": _f(_max_drawdown(series) * 100),
                    "beta_vs_benchmark": 1.0
                    if symbol == benchmark
                    else _f(_beta(returns, logret[benchmark])),
                    "correlation_vs_benchmark": 1.0
                    if symbol == benchmark
                    else _correlation(returns, logret[benchmark]),
                },
                "technicals": analysis.technicals(frames[symbol], per_year),
                # Rebased to 100 at the first shared bar, which is the only way
                # a $300 stock and a $40 ETF belong on one axis.
                "series": [
                    {"time": ts.isoformat(), "value": _f(v)}
                    for ts, v in (series / series.iloc[0] * 100).items()
                ],
            }
        )

    return {
        "symbols": out,
        "benchmark": benchmark,
        "interval": interval,
        "interval_label": spec.label,
        "bars": len(closes),
        "start": closes.index[0].isoformat(),
        "end": closes.index[-1].isoformat(),
        "correlations": _correlation_matrix(logret),
        "unavailable": [{"symbol": s, "reason": r} for s, r in failed.items()],
    }


def _correlation_matrix(logret: pd.DataFrame) -> dict:
    with np.errstate(invalid="ignore", divide="ignore"):
        matrix = logret.corr()
    return {
        "symbols": list(matrix.columns),
        "values": [[_f(matrix.iloc[i, j]) for j in range(len(matrix))] for i in range(len(matrix))],
    }


def explain_comparison(result: dict) -> list[dict]:
    """Plain-English reading of the comparison chart and table."""
    rows = result["symbols"]
    if not rows:
        return []

    ranked = sorted(
        rows, key=lambda r: (r["metrics"]["total_return_pct"] is None, -(r["metrics"]["total_return_pct"] or 0))
    )
    best, worst = ranked[0], ranked[-1]
    label = result["interval_label"].lower()

    out = [
        {
            "title": "What the chart shows",
            "body": (
                f"Every line starts at 100 on {result['start'][:10]} and tracks percentage "
                f"performance from there over {result['bars']} shared {label} bars — not price, "
                "so symbols at completely different price levels are comparable. Only bars where "
                "all symbols traded are used, so the same calendar applies to each."
            ),
        }
    ]

    if len(ranked) > 1 and best is not worst:
        spread = (best["metrics"]["total_return_pct"] or 0) - (worst["metrics"]["total_return_pct"] or 0)
        out.append(
            {
                "title": "Who led and who lagged",
                "body": (
                    f"{best['symbol']} returned {best['metrics']['total_return_pct']:+.2f}% over the "
                    f"window against {worst['metrics']['total_return_pct']:+.2f}% for "
                    f"{worst['symbol']} — a spread of {spread:.2f} points. Past performance over one "
                    "window is not evidence of anything repeatable; this is a description of what "
                    "happened, not a ranking of quality."
                ),
            }
        )

    riskiest = max(rows, key=lambda r: r["metrics"]["annualized_vol_pct"] or 0)
    calmest = min(rows, key=lambda r: r["metrics"]["annualized_vol_pct"] or float("inf"))
    if riskiest is not calmest:
        out.append(
            {
                "title": "Return is not the whole story",
                "body": (
                    f"{riskiest['symbol']} was the most volatile at "
                    f"{riskiest['metrics']['annualized_vol_pct']:.1f}% annualised, against "
                    f"{calmest['metrics']['annualized_vol_pct']:.1f}% for {calmest['symbol']}. The "
                    "return-per-unit-risk column divides one by the other, which is a fairer "
                    "comparison than return alone — a name that doubled while swinging 90% a year "
                    "did not necessarily do better than one that gained 20% quietly."
                ),
            }
        )

    others = [r for r in rows if r["symbol"] != result["benchmark"]]
    if others:
        tightest = max(others, key=lambda r: abs(r["metrics"]["correlation_vs_benchmark"] or 0))
        corr = tightest["metrics"]["correlation_vs_benchmark"]
        if corr is not None:
            reading = (
                "move together closely, so holding both spreads far less risk than it appears to"
                if corr > 0.8
                else "move largely independently, so they diversify each other"
                if corr < 0.4
                else "are moderately related"
            )
            out.append(
                {
                    "title": "How much they move together",
                    "body": (
                        f"{tightest['symbol']} has a correlation of {corr:.2f} with "
                        f"{result['benchmark']} over this window: the two {reading}. Beta "
                        f"({tightest['metrics']['beta_vs_benchmark']:.2f}) says how far "
                        f"{tightest['symbol']} tends to move when {result['benchmark']} moves 1%."
                    ),
                }
            )

    if result["unavailable"]:
        names = ", ".join(u["symbol"] for u in result["unavailable"])
        out.append(
            {
                "title": "Left out of this comparison",
                "body": (
                    f"{names} could not be included — see the note above the table. The remaining "
                    "symbols are compared over their own shared calendar."
                ),
            }
        )

    return out
