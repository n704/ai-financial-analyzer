"""Unit tests for the evaluation layer. No network and no model weights required."""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import analysis  # noqa: E402
from backend.app.market_data import future_timestamps  # noqa: E402


def daily_index(start, periods, freq="B", tz="America/New_York"):
    return pd.date_range(start, periods=periods, freq=freq, tz=tz)


# --------------------------------------------------------------- calendars


def test_equity_future_stamps_skip_weekends():
    idx = daily_index("2026-08-03", 10)  # Mon .. Fri
    out = future_timestamps(idx, "1d", 5)
    assert len(out) == 5
    assert all(ts.weekday() < 5 for ts in out)
    assert out[0] > idx[-1]


def test_crypto_future_stamps_include_weekends():
    idx = pd.date_range("2026-07-01", periods=40, freq="D", tz="UTC")
    out = future_timestamps(idx, "1d", 7)
    assert len(out) == 7
    assert any(ts.weekday() >= 5 for ts in out)
    # Strictly consecutive calendar days.
    assert (out[1:] - out[:-1]).unique().tolist() == [pd.Timedelta(days=1)]


def test_intraday_stamps_follow_the_session_grid():
    # 9:30 -> 15:30 hourly bars over three sessions.
    stamps = [
        pd.Timestamp(f"2026-08-{d:02d} {h:02d}:30", tz="America/New_York")
        for d in (5, 6, 7)
        for h in range(9, 16)
    ]
    idx = pd.DatetimeIndex(stamps)
    out = future_timestamps(idx, "1h", 9)
    assert len(out) == 9
    # Next session resumes at the open, never overnight.
    assert {ts.hour for ts in out} <= set(range(9, 16))
    assert out[0] == pd.Timestamp("2026-08-10 09:30", tz="America/New_York")
    assert all(ts.weekday() < 5 for ts in out)


def test_intraday_stamps_are_strictly_increasing():
    idx = pd.date_range("2026-08-03 00:00", periods=200, freq="1h", tz="UTC")
    out = future_timestamps(idx, "1h", 30)
    assert list(out) == sorted(out)
    assert len(set(out)) == 30


# --------------------------------------------------------------- forecasts


def make_paths(n_paths, pred_len, start=100.0, drift=0.0, spread=0.0, seed=0):
    """Synthetic (n_paths, pred_len, 6) forecast tensor with a known outcome."""
    rng = np.random.default_rng(seed)
    out = np.zeros((n_paths, pred_len, 6))
    for i in range(n_paths):
        offset = (i - (n_paths - 1) / 2) * spread
        closes = start * (1 + drift * np.arange(1, pred_len + 1) / pred_len) + offset
        out[i, :, 0] = closes
        out[i, :, 1] = closes * 1.01
        out[i, :, 2] = closes * 0.99
        out[i, :, 3] = closes
        out[i, :, 4] = rng.uniform(1e5, 2e5, pred_len)
        out[i, :, 5] = out[i, :, 4] * closes
    return out


def test_summary_flags_a_clear_uptrend_as_buy():
    paths = make_paths(20, 10, drift=0.08, spread=0.5)
    idx = daily_index("2026-08-12", 10)
    s = analysis.forecast_summary(paths, idx, last_close=100.0, interval="1d")

    assert s["signal"]["action"] == "BUY"
    assert s["stats"]["prob_up"] == 1.0
    assert s["stats"]["expected_return_pct"] == pytest.approx(8.0, abs=0.5)
    assert s["stats"]["close_p10"] < s["stats"]["median_close"] < s["stats"]["close_p90"]
    assert len(s["band"]) == 10


def test_summary_flags_a_clear_downtrend_as_sell():
    paths = make_paths(20, 10, drift=-0.08, spread=0.5)
    s = analysis.forecast_summary(paths, daily_index("2026-08-12", 10), last_close=100.0, interval="1d")
    assert s["signal"]["action"] == "SELL"
    assert s["stats"]["expected_return_pct"] < 0


def test_flat_forecast_holds_and_caps_confidence():
    paths = make_paths(20, 10, drift=0.0, spread=2.0)
    s = analysis.forecast_summary(paths, daily_index("2026-08-12", 10), last_close=100.0, interval="1d")
    assert s["signal"]["action"] == "HOLD"
    assert s["signal"]["confidence"] <= 55


def test_band_candles_keep_ohlc_ordering():
    paths = make_paths(12, 6, drift=0.05, spread=1.0)
    s = analysis.forecast_summary(paths, daily_index("2026-08-12", 6), last_close=100.0, interval="1d")
    for bar in s["band"]:
        assert bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]
        assert bar["p10"] <= bar["p50"] <= bar["p90"]


def test_summary_is_json_safe_with_degenerate_paths():
    """Zero-variance paths must not emit NaN/Inf into the API response."""
    paths = make_paths(4, 5, drift=0.0, spread=0.0)
    s = analysis.forecast_summary(paths, daily_index("2026-08-12", 5), last_close=100.0, interval="1d")
    for value in s["stats"].values():
        assert value is None or np.isfinite(value)


# --------------------------------------------------------------- hold-out


def _frame(values, index):
    return pd.DataFrame({"open": values, "high": values, "low": values, "close": values,
                         "volume": np.full(len(values), 1e6)}, index=index)


def test_holdout_scores_a_perfect_forecast():
    idx_ctx = daily_index("2026-06-01", 20)
    idx_act = daily_index("2026-07-01", 5)
    truth = np.array([101.0, 102.0, 103.0, 104.0, 105.0])
    paths = np.zeros((6, 5, 6))
    paths[:, :, 3] = truth

    bt = analysis.holdout_evaluation(_frame(np.full(20, 100.0), idx_ctx), paths, _frame(truth, idx_act))
    assert bt["mape_pct"] == pytest.approx(0.0, abs=1e-9)
    assert bt["directional_hit_rate_pct"] == 100.0
    assert bt["terminal_direction_correct"] is True
    assert bt["beats_naive"] is True
    assert len(bt["series"]) == 5


def test_holdout_detects_a_forecast_worse_than_flat():
    idx_ctx = daily_index("2026-06-01", 20)
    idx_act = daily_index("2026-07-01", 5)
    truth = np.full(5, 100.0)
    paths = np.zeros((6, 5, 6))
    paths[:, :, 3] = 130.0  # confidently wrong

    bt = analysis.holdout_evaluation(_frame(np.full(20, 100.0), idx_ctx), paths, _frame(truth, idx_act))
    assert bt["beats_naive"] is False
    assert bt["mape_pct"] == pytest.approx(30.0)
    assert bt["naive_mape_pct"] == pytest.approx(0.0)


# ------------------------------------------------------------ diagnostics


def test_stretched_context_raises_a_mean_reversion_caveat():
    idx = daily_index("2026-01-01", 200)
    ctx = _frame(np.linspace(100, 200, 200), idx)  # last close far above window mean
    diag = analysis.diagnostics(ctx, "1d", 200, backtest=None)
    assert diag["context_z"] > 1.5
    assert any("mean-revert" in c for c in diag["caveats"])


def test_long_daily_lookback_is_flagged():
    idx = daily_index("2026-01-01", 260)
    ctx = _frame(np.full(260, 100.0) + np.sin(np.arange(260)), idx)
    diag = analysis.diagnostics(ctx, "1d", 260, backtest=None)
    assert any("walk-forward" in c for c in diag["caveats"])


def test_quiet_context_produces_no_caveats():
    idx = daily_index("2026-01-01", 128)
    ctx = _frame(100 + np.sin(np.arange(128) / 3), idx)
    diag = analysis.diagnostics(ctx, "1d", 128, backtest=None)
    assert diag["caveats"] == []


# -------------------------------------------------------------------- api


def test_config_and_health_endpoints_do_not_need_the_model():
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app) as client:
        cfg = client.get("/api/config").json()
        assert {"intervals", "models", "defaults", "limits"} <= cfg.keys()
        assert cfg["defaults"]["lookback"] == 128

        health = client.get("/api/health").json()
        assert health["status"] == "ok"

        bad = client.post("/api/analyze", json={"symbol": "AAPL", "lookback": 9999})
        assert bad.status_code == 422
