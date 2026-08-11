"""Chart explanations. Prose is derived from the stats, so it must track them."""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import analysis, narrative  # noqa: E402

from test_app import daily_index, make_paths  # noqa: E402


def summary(drift=0.05, spread=1.0, n_paths=20, pred_len=10):
    paths = make_paths(n_paths, pred_len, drift=drift, spread=spread)
    return analysis.forecast_summary(paths, daily_index("2026-08-12", pred_len), 100.0, "1d")


PARAMS = {"horizon": 10, "lookback": 128, "paths": 20}
TECHNICALS = {"realized_vol_annual": 0.25}


def text(paragraphs):
    return " ".join(f"{p['title']} {p['body']}" for p in paragraphs)


def forecast_text(**kw):
    s = summary(**kw)
    return text(narrative.explain_forecast(s["stats"], s["band"], PARAMS, "Daily", TECHNICALS))


# --------------------------------------------------------------- structure


def test_every_paragraph_has_a_title_and_a_body():
    s = summary()
    for p in narrative.explain_forecast(s["stats"], s["band"], PARAMS, "Daily", TECHNICALS):
        assert p["title"].strip()
        assert len(p["body"].strip()) > 40


def test_the_forecast_explanation_covers_all_four_topics():
    s = summary()
    titles = [p["title"] for p in narrative.explain_forecast(s["stats"], s["band"], PARAMS, "Daily", TECHNICALS)]
    assert len(titles) == 4
    assert len(set(titles)) == 4


# --------------------------------------------------------------- direction


def test_an_uptrend_reads_as_rising():
    body = forecast_text(drift=0.08)
    assert "rises" in body
    assert "falls" not in body


def test_a_downtrend_reads_as_falling():
    body = forecast_text(drift=-0.08)
    assert "falls" in body
    assert "rises" not in body


def test_the_stated_move_matches_the_computed_return():
    s = summary(drift=0.08)
    body = text(narrative.explain_forecast(s["stats"], s["band"], PARAMS, "Daily", TECHNICALS))
    assert f"{s['stats']['expected_return_pct']:+.2f}%" in body


def test_the_path_count_is_reported_accurately():
    assert "37 separate futures" in forecast_text(n_paths=37)


# ------------------------------------------------------------- band width


def test_a_wide_band_is_called_wide():
    """Spread far beyond what 25% annual vol implies over 10 bars."""
    assert "hedging" in forecast_text(drift=0.0, spread=12.0)


def test_a_tight_band_is_called_tight():
    assert "tighter than history" in forecast_text(drift=0.0, spread=0.05)


def test_a_normal_band_is_not_flagged():
    """spread=1.0 puts the band at ~1.2x the 25%-vol baseline: unremarkable."""
    body = forecast_text(drift=0.01, spread=1.0)
    assert "in line with how this stock normally moves" in body
    assert "hedging" not in body
    assert "tighter than history" not in body


def test_without_a_volatility_baseline_it_says_so():
    s = summary()
    body = text(narrative.explain_forecast(s["stats"], s["band"], PARAMS, "Daily", technicals=None))
    assert "no realized-volatility baseline" in body


# ------------------------------------------------------------- conviction


def test_agreeing_paths_read_as_high_conviction():
    assert "which is high" in forecast_text(drift=0.08, spread=0.2)


def test_disagreeing_paths_read_as_noise():
    assert "noise more than signal" in forecast_text(drift=0.0005, spread=8.0)


def test_probability_is_qualified_not_stated_as_truth():
    body = forecast_text()
    assert "not a probability the stock goes up" in body


# ----------------------------------------------------------------- degenerate


def test_none_values_do_not_raise():
    """`analysis._f` emits None for non-finite stats; every branch must cope."""
    stats = dict.fromkeys(
        [
            "n_paths", "horizon_bars", "last_close", "expected_close", "median_close",
            "close_p10", "close_p90", "expected_return_pct", "median_return_pct",
            "return_p10_pct", "return_p90_pct", "prob_up", "dispersion_pct", "conviction",
            "forecast_vol_annual", "max_drawdown_pct", "value_at_risk_5pct",
            "expected_shortfall_5pct",
        ]
    )
    out = narrative.explain_forecast(stats, [], PARAMS, "Daily", None)
    assert len(out) == 4
    assert all(p["body"] for p in out)


def test_zero_variance_paths_are_described_not_crashed_on():
    s = summary(drift=0.0, spread=0.0)
    body = text(narrative.explain_forecast(s["stats"], s["band"], PARAMS, "Daily", TECHNICALS))
    assert body.strip()


def test_a_single_bar_horizon_reads_grammatically():
    s = summary(pred_len=1)
    body = text(narrative.explain_forecast(s["stats"], s["band"], {"horizon": 1}, "Daily", TECHNICALS))
    assert "1 daily bar " in body
    assert "1 daily bars" not in body


# ------------------------------------------------------------------ hold-out


def _frame(values, index):
    return pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values,
         "volume": np.full(len(values), 1e6)},
        index=index,
    )


def holdout(truth, predicted, spread=1.0):
    idx_ctx, idx_act = daily_index("2026-06-01", 20), daily_index("2026-07-01", len(truth))
    paths = np.zeros((8, len(truth), 6))
    for i in range(8):
        paths[i, :, 3] = np.asarray(predicted) + (i - 3.5) * spread
    return analysis.holdout_evaluation(
        _frame(np.full(20, 100.0), idx_ctx), paths, _frame(np.asarray(truth, dtype=float), idx_act)
    )


def test_no_backtest_means_no_paragraphs():
    assert narrative.explain_backtest(None) == []


def test_a_win_against_the_baseline_is_stated_plainly():
    bt = holdout([101.0, 102.0, 103.0], [101.0, 102.0, 103.0], spread=0.1)
    body = text(narrative.explain_backtest(bt))
    assert "beat that baseline" in body


def test_a_loss_against_the_baseline_is_not_softened():
    bt = holdout([100.0, 100.0, 100.0], [130.0, 130.0, 130.0])
    body = text(narrative.explain_backtest(bt))
    assert "lost to that baseline" in body
    assert "not adding information" in body


def test_an_overconfident_band_is_called_out():
    bt = holdout([100.0, 130.0, 160.0], [100.0, 100.0, 100.0], spread=0.01)
    body = text(narrative.explain_backtest(bt))
    assert "too narrow" in body


def test_an_uselessly_wide_band_is_called_out():
    bt = holdout([100.0, 101.0, 102.0], [100.0, 101.0, 102.0], spread=40.0)
    body = text(narrative.explain_backtest(bt))
    assert "almost useless" in body


def test_the_reported_error_matches_the_backtest_numbers():
    bt = holdout([100.0, 100.0, 100.0], [130.0, 130.0, 130.0])
    body = text(narrative.explain_backtest(bt))
    assert f"{bt['mape_pct']:.2f}%" in body
    assert f"{bt['naive_mape_pct']:.2f}%" in body


# --------------------------------------------------------------- assembly


def test_explain_builds_both_sections():
    s = summary()
    result = {
        "stats": s["stats"],
        "forecast": {"band": s["band"]},
        "params": PARAMS,
        "interval_label": "Daily",
        "technicals": TECHNICALS,
        "backtest": holdout([101.0, 102.0], [101.0, 102.0], spread=0.1),
    }
    out = narrative.explain(result)
    assert set(out) == {"forecast", "backtest"}
    assert out["forecast"] and out["backtest"]


def test_explain_tolerates_a_response_without_a_backtest():
    s = summary()
    out = narrative.explain(
        {
            "stats": s["stats"],
            "forecast": {"band": s["band"]},
            "params": PARAMS,
            "interval_label": "Daily",
            "technicals": TECHNICALS,
            "backtest": None,
        }
    )
    assert out["backtest"] == []
