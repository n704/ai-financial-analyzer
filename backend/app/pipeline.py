"""Orchestrates: market data -> Kronos forecast -> evaluation payload."""
from __future__ import annotations

import time

from . import analysis, narrative
from .kronos_engine import engine
from .market_data import INTERVALS, MarketDataError, fetch_ohlcv, future_timestamps
from .schemas import AnalyzeRequest

DISCLAIMER = (
    "Kronos is a probabilistic time-series model, not an oracle. These forecasts are "
    "generated from price history alone — no fundamentals, news or earnings — and are for "
    "research and education only. Nothing here is financial advice."
)

# Fetch at least this much history so indicators (SMA-200, 52-week range) are
# meaningful even when the model is fed a short context window.
MIN_HISTORY_BARS = 260


def analyze(req: AnalyzeRequest) -> dict:
    """Run the full evaluation for one symbol."""
    timings: dict[str, int] = {}
    spec = INTERVALS.get(req.interval)
    if spec is None:
        raise MarketDataError(f"Unsupported interval '{req.interval}'.")

    t0 = time.time()
    # Extra bars so the hold-out backtest still gets a full context window.
    need = max(req.lookback + (req.horizon if req.backtest else 0), MIN_HISTORY_BARS)
    md = fetch_ohlcv(req.symbol, req.interval, need)
    timings["market_data"] = int((time.time() - t0) * 1000)

    df = md.df
    backtest_possible = req.backtest and len(df) >= req.horizon + 64

    context = df.tail(req.lookback)
    future_index = future_timestamps(df.index, req.interval, req.horizon)

    t0 = time.time()
    paths = engine.forecast_paths(
        context,
        context.index,
        future_index,
        n_paths=req.paths,
        temperature=req.temperature,
        top_p=req.top_p,
        seed=req.seed,
    )
    timings["forecast"] = int((time.time() - t0) * 1000)

    last_close = float(context["close"].iloc[-1])
    summary = analysis.forecast_summary(paths, future_index, last_close, req.interval)

    backtest = None
    if backtest_possible:
        t0 = time.time()
        actual = df.tail(req.horizon)
        bt_context = df.iloc[: -req.horizon].tail(req.lookback)
        bt_paths = engine.forecast_paths(
            bt_context,
            bt_context.index,
            actual.index,
            n_paths=req.paths,
            temperature=req.temperature,
            top_p=req.top_p,
            seed=req.seed,
        )
        backtest = analysis.holdout_evaluation(bt_context, bt_paths, actual)
        timings["backtest"] = int((time.time() - t0) * 1000)

    result = {
        "symbol": md.symbol,
        "meta": md.meta,
        "interval": req.interval,
        "interval_label": spec.label,
        "params": {
            "lookback": len(context),
            "horizon": req.horizon,
            "paths": req.paths,
            "temperature": req.temperature,
            "top_p": req.top_p,
            "seed": req.seed,
            "history_bars": len(df),
            "history_start": df.index[0].isoformat(),
            "context_start": context.index[0].isoformat(),
            "history_end": df.index[-1].isoformat(),
            "forecast_end": future_index[-1].isoformat(),
        },
        "model": engine.status(),
        # Chart the full download; the model only ever saw the last `lookback` bars.
        "history": analysis.candles(df),
        "technicals": analysis.technicals(df, spec.bars_per_year),
        "forecast": {"band": summary["band"], "sample_paths": summary["sample_paths"]},
        "signal": summary["signal"],
        "stats": summary["stats"],
        "backtest": backtest,
        "diagnostics": analysis.diagnostics(context, req.interval, len(context), backtest),
        "timings_ms": timings,
        "disclaimer": DISCLAIMER,
    }
    # Prose read off the numbers above, so it can never contradict the charts.
    result["explanations"] = narrative.explain(result)
    return result
