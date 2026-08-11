"""Turn raw Kronos forecast paths into an interpretable stock evaluation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .market_data import INTERVALS

CLOSE = 3  # column index of `close` in a forecast path
OPEN, HIGH, LOW = 0, 1, 2
VOLUME = 4

# Terminal-return magnitude below which a directional call is not worth making.
MIN_EDGE = 0.005


def _f(x) -> float | None:
    """JSON-safe float."""
    if x is None:
        return None
    x = float(x)
    return x if np.isfinite(x) else None


def _pct(a: np.ndarray, q: float) -> np.ndarray:
    return np.percentile(a, q, axis=0)


def candles(df: pd.DataFrame) -> list[dict]:
    return [
        {
            "time": ts.isoformat(),
            "open": _f(row.open),
            "high": _f(row.high),
            "low": _f(row.low),
            "close": _f(row.close),
            "volume": _f(row.volume),
        }
        for ts, row in zip(df.index, df.itertuples())
    ]


def technicals(df: pd.DataFrame, bars_per_year: float) -> dict:
    close = df["close"]
    logret = np.log(close / close.shift(1)).dropna()

    def sma(n: int):
        return _f(close.rolling(n).mean().iloc[-1]) if len(close) >= n else None

    rsi = None
    if len(close) > 15:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
        loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
        if loss and loss > 0:
            rsi = _f(100 - 100 / (1 + gain / loss))
        elif gain and gain > 0:
            rsi = 100.0

    window = close.tail(int(min(len(close), bars_per_year)))
    hi, lo = float(window.max()), float(window.min())
    last = float(close.iloc[-1])

    return {
        "last_close": _f(last),
        "sma_20": sma(20),
        "sma_50": sma(50),
        "sma_200": sma(200),
        "rsi_14": rsi,
        "realized_vol_annual": _f(logret.std() * np.sqrt(bars_per_year)) if len(logret) > 2 else None,
        "period_high": _f(hi),
        "period_low": _f(lo),
        "pct_from_high": _f((last / hi - 1) * 100) if hi else None,
        "pct_from_low": _f((last / lo - 1) * 100) if lo else None,
    }


def forecast_summary(
    paths: np.ndarray,
    future_index: pd.DatetimeIndex,
    last_close: float,
    interval: str,
    max_sample_paths: int = 12,
) -> dict:
    """Aggregate Monte-Carlo paths into bands, statistics and a signal."""
    closes = paths[:, :, CLOSE]
    n_paths, pred_len = closes.shape
    bars_per_year = INTERVALS[interval].bars_per_year

    p10, p25, p50, p75, p90 = (_pct(closes, q) for q in (10, 25, 50, 75, 90))

    med_open, med_high = _pct(paths[:, :, OPEN], 50), _pct(paths[:, :, HIGH], 50)
    med_low, med_close = _pct(paths[:, :, LOW], 50), p50
    med_volume = _pct(paths[:, :, VOLUME], 50)

    band = []
    for i, ts in enumerate(future_index):
        # Per-step medians are taken independently, so re-impose OHLC ordering
        # before the frontend tries to draw them as candles.
        o, h, l, c = med_open[i], med_high[i], med_low[i], med_close[i]
        band.append(
            {
                "time": ts.isoformat(),
                "open": _f(o),
                "high": _f(max(o, h, l, c)),
                "low": _f(min(o, h, l, c)),
                "close": _f(c),
                "volume": _f(med_volume[i]),
                "p10": _f(p10[i]),
                "p25": _f(p25[i]),
                "p50": _f(p50[i]),
                "p75": _f(p75[i]),
                "p90": _f(p90[i]),
            }
        )

    terminal = closes[:, -1]
    returns = terminal / last_close - 1.0
    exp_ret = float(np.mean(returns))
    std_ret = float(np.std(returns))
    prob_up = float(np.mean(terminal > last_close))

    step_logret = np.diff(np.log(np.maximum(closes, 1e-9)), axis=1)
    fwd_vol = float(np.std(step_logret) * np.sqrt(bars_per_year)) if step_logret.size else float("nan")

    running_max = np.maximum.accumulate(p50)
    max_dd = float(np.min(p50 / running_max - 1.0))

    signal, confidence, rationale = _signal(exp_ret, std_ret, prob_up, returns)

    sample_idx = np.linspace(0, n_paths - 1, min(max_sample_paths, n_paths)).astype(int)
    sample_paths = [
        [{"time": ts.isoformat(), "value": _f(v)} for ts, v in zip(future_index, closes[i])]
        for i in np.unique(sample_idx)
    ]

    return {
        "band": band,
        "sample_paths": sample_paths,
        "stats": {
            "n_paths": n_paths,
            "horizon_bars": pred_len,
            "last_close": _f(last_close),
            "expected_close": _f(float(np.mean(terminal))),
            "median_close": _f(float(np.median(terminal))),
            "close_p10": _f(float(np.percentile(terminal, 10))),
            "close_p90": _f(float(np.percentile(terminal, 90))),
            "expected_return_pct": _f(exp_ret * 100),
            "median_return_pct": _f(float(np.median(returns)) * 100),
            "return_p10_pct": _f(float(np.percentile(returns, 10)) * 100),
            "return_p90_pct": _f(float(np.percentile(returns, 90)) * 100),
            "prob_up": _f(prob_up),
            "dispersion_pct": _f(std_ret * 100),
            "conviction": _f(exp_ret / std_ret if std_ret > 1e-12 else 0.0),
            "forecast_vol_annual": _f(fwd_vol),
            "max_drawdown_pct": _f(max_dd * 100),
            "value_at_risk_5pct": _f(float(np.percentile(returns, 5)) * 100),
            "expected_shortfall_5pct": _f(
                float(np.mean(returns[returns <= np.percentile(returns, 5)])) * 100
            ),
        },
        "signal": {"action": signal, "confidence": confidence, "rationale": rationale},
    }


def _signal(exp_ret: float, std_ret: float, prob_up: float, returns: np.ndarray):
    conviction = exp_ret / std_ret if std_ret > 1e-12 else 0.0

    if prob_up >= 0.58 and exp_ret > MIN_EDGE:
        action = "BUY"
    elif prob_up <= 0.42 and exp_ret < -MIN_EDGE:
        action = "SELL"
    else:
        action = "HOLD"

    directional = abs(2 * prob_up - 1)
    confidence = int(round(100 * min(1.0, 0.6 * directional + 0.4 * min(1.0, abs(conviction) / 1.5))))
    if action == "HOLD":
        confidence = min(confidence, 55)

    downside = float(np.percentile(returns, 5)) * 100
    upside = float(np.percentile(returns, 95)) * 100
    rationale = [
        f"{prob_up * 100:.0f}% of {len(returns)} sampled Kronos futures end above the current price.",
        f"Mean modelled return over the horizon is {exp_ret * 100:+.2f}% "
        f"with a {std_ret * 100:.2f}% spread across paths (conviction {conviction:+.2f}).",
        f"5th–95th percentile outcome range: {downside:+.2f}% to {upside:+.2f}%.",
    ]
    if action == "HOLD":
        rationale.append(
            "Neither direction clears the edge threshold "
            f"(needs >{MIN_EDGE * 100:.1f}% expected move and >58% / <42% probability), so no directional call."
        )
    return action, confidence, rationale


def diagnostics(context: pd.DataFrame, interval: str, lookback: int, backtest: dict | None) -> dict:
    """Flag the conditions under which these forecasts are least trustworthy."""
    close = context["close"]
    std = float(close.std())
    z = float((close.iloc[-1] - close.mean()) / std) if std > 1e-9 else 0.0

    caveats: list[str] = []
    if abs(z) > 1.5:
        caveats.append(
            f"The latest close sits {z:+.1f}σ from the mean of the {lookback}-bar context window. "
            "Kronos z-scores each window before forecasting, and it mean-reverts hard from stretched "
            "windows — expect the drift to lean against the trend. A shorter lookback reduces this."
        )
    if interval == "1d" and lookback > 200:
        caveats.append(
            f"A {lookback}-bar daily lookback is in the range that scored worst in walk-forward testing "
            "(MAPE ~6.9% at 400 bars vs ~3.6% at 64). Consider 64–128 bars."
        )
    if backtest and not backtest["beats_naive"]:
        caveats.append(
            f"On the {backtest['bars']} withheld bars the forecast missed by "
            f"{backtest['mape_pct']:.2f}% against {backtest['naive_mape_pct']:.2f}% for a flat-price "
            "baseline, so this configuration did not beat 'assume no change' on recent data."
        )
    return {"context_z": _f(z), "caveats": caveats}


def holdout_evaluation(
    hist: pd.DataFrame,
    paths: np.ndarray,
    actual: pd.DataFrame,
) -> dict:
    """Score a forecast made for bars that already happened.

    `hist` is the context window, `actual` the withheld bars, `paths` the
    forecast produced from `hist` alone.
    """
    closes = paths[:, :, CLOSE]
    median = np.percentile(closes, 50, axis=0)
    p10 = np.percentile(closes, 10, axis=0)
    p90 = np.percentile(closes, 90, axis=0)
    truth = actual["close"].to_numpy(dtype=float)
    anchor = float(hist["close"].iloc[-1])

    mape = float(np.mean(np.abs(median - truth) / np.abs(truth)) * 100)
    rmse = float(np.sqrt(np.mean((median - truth) ** 2)))
    naive_mape = float(np.mean(np.abs(anchor - truth) / np.abs(truth)) * 100)

    pred_steps = np.sign(np.diff(np.concatenate([[anchor], median])))
    true_steps = np.sign(np.diff(np.concatenate([[anchor], truth])))
    hit_rate = float(np.mean(pred_steps == true_steps) * 100)

    coverage = float(np.mean((truth >= p10) & (truth <= p90)) * 100)
    pred_dir = "up" if median[-1] >= anchor else "down"
    true_dir = "up" if truth[-1] >= anchor else "down"

    return {
        "bars": len(truth),
        "mape_pct": _f(mape),
        "naive_mape_pct": _f(naive_mape),
        "beats_naive": bool(mape < naive_mape),
        "rmse": _f(rmse),
        "directional_hit_rate_pct": _f(hit_rate),
        "band_coverage_pct": _f(coverage),
        "terminal_direction_correct": pred_dir == true_dir,
        "series": [
            {
                "time": ts.isoformat(),
                "actual": _f(t),
                "predicted": _f(m),
                "p10": _f(a),
                "p90": _f(b),
            }
            for ts, t, m, a, b in zip(actual.index, truth, median, p10, p90)
        ],
    }
