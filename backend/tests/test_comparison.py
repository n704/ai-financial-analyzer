"""Multi-symbol comparison maths. Synthetic frames, no network, no model."""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import comparison, market_data  # noqa: E402
from backend.app.market_data import MarketData, MarketDataError  # noqa: E402


def frame(closes, start="2026-01-01", freq="B", tz="America/New_York"):
    idx = pd.date_range(start, periods=len(closes), freq=freq, tz=tz)
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": np.full(len(closes), 1e6),
        },
        index=idx,
    )


def install(monkeypatch, data: dict[str, pd.DataFrame], names=None, missing=()):
    """Point `fetch_ohlcv` at fixed frames."""

    def fake(symbol, interval, bars):
        if symbol in missing:
            raise MarketDataError(f"No market data returned for '{symbol}'.")
        return MarketData(
            symbol,
            interval,
            data[symbol],
            {"symbol": symbol, "name": (names or {}).get(symbol, symbol), "currency": "USD"},
        )

    monkeypatch.setattr(comparison, "fetch_ohlcv", fake)


@pytest.fixture(autouse=True)
def _clean():
    market_data.clear_caches()
    yield
    market_data.clear_caches()


def rising(n=60, rate=0.01, start=100.0, seed=0, noise=0.012):
    """A drifting random walk.

    Deliberately not a constant compounding rate: that has zero return
    variance, which makes beta and correlation genuinely undefined and would
    test the degenerate path rather than the intended one.
    """
    rng = np.random.default_rng(seed)
    return start * np.cumprod(1 + rate + rng.normal(0, noise, n))


# ------------------------------------------------------------------ inputs


def test_fewer_than_two_symbols_is_rejected(monkeypatch):
    install(monkeypatch, {"AAPL": frame(rising())})
    with pytest.raises(MarketDataError, match="at least"):
        comparison.compare_symbols(["AAPL"])


def test_duplicate_symbols_collapse(monkeypatch):
    install(monkeypatch, {"AAPL": frame(rising()), "MSFT": frame(rising())})
    out = comparison.compare_symbols(["aapl", "AAPL", "msft"])
    assert [r["symbol"] for r in out["symbols"]] == ["AAPL", "MSFT"]


def test_too_many_symbols_is_rejected(monkeypatch):
    symbols = [f"S{i}" for i in range(comparison.MAX_SYMBOLS + 1)]
    install(monkeypatch, {s: frame(rising()) for s in symbols})
    with pytest.raises(MarketDataError, match="limit"):
        comparison.compare_symbols(symbols)


def test_an_unsupported_interval_is_rejected(monkeypatch):
    install(monkeypatch, {"AAPL": frame(rising()), "MSFT": frame(rising())})
    with pytest.raises(MarketDataError, match="interval"):
        comparison.compare_symbols(["AAPL", "MSFT"], interval="1w")


# ----------------------------------------------------------------- metrics


def test_identical_series_have_beta_and_correlation_of_one(monkeypatch):
    series = rising()
    install(monkeypatch, {"AAPL": frame(series), "MSFT": frame(series)})
    out = comparison.compare_symbols(["AAPL", "MSFT"])
    other = out["symbols"][1]["metrics"]
    assert other["beta_vs_benchmark"] == pytest.approx(1.0)
    assert other["correlation_vs_benchmark"] == pytest.approx(1.0)


def test_a_doubly_sensitive_series_has_beta_two(monkeypatch):
    """A series whose every log move is twice the benchmark's has beta 2."""
    base = np.log(rising(120, 0.001))
    levered = np.exp(base[0] + 2 * (base - base[0]))
    install(monkeypatch, {"AAPL": frame(np.exp(base)), "LEVER": frame(levered)})
    out = comparison.compare_symbols(["AAPL", "LEVER"])
    assert out["symbols"][1]["metrics"]["beta_vs_benchmark"] == pytest.approx(2.0, abs=0.01)


def test_total_return_matches_the_underlying_move(monkeypatch):
    install(monkeypatch, {"AAPL": frame([100.0] * 30 + [150.0]), "MSFT": frame(rising(31))})
    out = comparison.compare_symbols(["AAPL", "MSFT"])
    assert out["symbols"][0]["metrics"]["total_return_pct"] == pytest.approx(50.0)


def test_max_drawdown_is_measured_peak_to_trough(monkeypatch):
    install(
        monkeypatch,
        {"AAPL": frame([100.0] * 10 + [200.0] + [150.0] * 20), "MSFT": frame(rising(31))},
    )
    assert out_dd(monkeypatch) == pytest.approx(-25.0)


def out_dd(monkeypatch):
    out = comparison.compare_symbols(["AAPL", "MSFT"])
    return out["symbols"][0]["metrics"]["max_drawdown_pct"]


def test_the_first_symbol_is_the_benchmark(monkeypatch):
    install(monkeypatch, {"AAPL": frame(rising()), "MSFT": frame(rising(60, 0.005))})
    out = comparison.compare_symbols(["MSFT", "AAPL"])
    assert out["benchmark"] == "MSFT"
    assert out["symbols"][0]["metrics"]["beta_vs_benchmark"] == 1.0


def test_technicals_are_reused_not_reimplemented(monkeypatch):
    install(monkeypatch, {"AAPL": frame(rising()), "MSFT": frame(rising())})
    out = comparison.compare_symbols(["AAPL", "MSFT"])
    assert "rsi_14" in out["symbols"][0]["technicals"]
    assert "sma_20" in out["symbols"][0]["technicals"]


def test_a_flat_series_does_not_emit_nan(monkeypatch):
    install(monkeypatch, {"FLAT": frame([100.0] * 60), "MSFT": frame(rising())})
    out = comparison.compare_symbols(["FLAT", "MSFT"])
    for row in out["symbols"]:
        for value in row["metrics"].values():
            assert value is None or np.isfinite(value)


# --------------------------------------------------------------- rebasing


def test_series_are_rebased_to_a_common_start(monkeypatch):
    install(monkeypatch, {"CHEAP": frame(rising(40, 0.01, 5.0)), "RICH": frame(rising(40, 0.01, 900.0))})
    out = comparison.compare_symbols(["CHEAP", "RICH"])
    for row in out["symbols"]:
        assert row["series"][0]["value"] == pytest.approx(100.0)
    # Same growth rate from very different prices must overlay exactly.
    assert out["symbols"][0]["series"][-1]["value"] == pytest.approx(
        out["symbols"][1]["series"][-1]["value"]
    )


def test_last_close_keeps_the_real_price(monkeypatch):
    """Rebasing is for the chart only; the table must show actual prices."""
    install(monkeypatch, {"CHEAP": frame([5.0] * 40), "RICH": frame([900.0] * 40)})
    out = comparison.compare_symbols(["CHEAP", "RICH"])
    assert out["symbols"][0]["last_close"] == pytest.approx(5.0)
    assert out["symbols"][1]["last_close"] == pytest.approx(900.0)
    assert out["symbols"][0]["series"][-1]["value"] == pytest.approx(100.0)


# --------------------------------------------------------------- alignment


def test_misaligned_calendars_are_inner_joined(monkeypatch):
    """A 7-day crypto calendar against a 5-day equity one must compare only
    the days both traded, not silently different windows."""
    equity = frame(rising(40), start="2026-01-05", freq="B")
    crypto = frame(rising(56), start="2026-01-05", freq="D")
    install(monkeypatch, {"AAPL": equity, "BTC-USD": crypto})

    out = comparison.compare_symbols(["AAPL", "BTC-USD"])
    assert out["bars"] == 40  # weekdays only
    assert out["bars"] < len(crypto)
    assert len(out["symbols"][0]["series"]) == out["bars"]


def test_daily_bars_align_across_time_zones(monkeypatch):
    """Regression: AAPL's bars are stamped 00:00 New York and BTC-USD's 00:00
    UTC. Joining on the exact instant found zero overlap, so a perfectly
    comparable crypto symbol was silently dropped from every comparison."""
    equity = frame(rising(70), start="2026-01-05", freq="B", tz="America/New_York")
    crypto = frame(rising(98), start="2026-01-05", freq="D", tz="UTC")
    install(monkeypatch, {"AAPL": equity, "BTC-USD": crypto})

    out = comparison.compare_symbols(["AAPL", "BTC-USD"])
    assert out["unavailable"] == []
    assert [r["symbol"] for r in out["symbols"]] == ["AAPL", "BTC-USD"]
    # Weekdays only, because that is when the equity traded.
    assert out["bars"] == 70


def test_a_tokyo_listing_keeps_its_own_calendar_day(monkeypatch):
    """Converting to UTC would shift a 00:00 JST bar to the previous day."""
    ny = frame(rising(60), start="2026-01-05", freq="B", tz="America/New_York")
    tokyo = frame(rising(60), start="2026-01-05", freq="B", tz="Asia/Tokyo")
    install(monkeypatch, {"AAPL": ny, "7203.T": tokyo})

    out = comparison.compare_symbols(["AAPL", "7203.T"])
    assert out["bars"] == 60
    assert out["unavailable"] == []


def test_intraday_bars_align_on_the_actual_instant(monkeypatch):
    """A 09:30 New York bar and the 14:30 UTC bar are the same moment."""
    ny = frame(rising(60), start="2026-08-03 09:30", freq="1h", tz="America/New_York")
    utc = frame(rising(60), start="2026-08-03 13:30", freq="1h", tz="UTC")
    install(monkeypatch, {"AAPL": ny, "BTC-USD": utc})

    out = comparison.compare_symbols(["AAPL", "BTC-USD"], interval="1h")
    assert out["bars"] == 60
    assert out["unavailable"] == []


def test_symbols_sharing_no_history_at_all_raise(monkeypatch):
    install(
        monkeypatch,
        {
            "OLD": frame(rising(60), start="2019-01-07"),
            "NEW": frame(rising(60), start="2026-01-05"),
        },
    )
    with pytest.raises(MarketDataError, match="do not share enough history"):
        comparison.compare_symbols(["OLD", "NEW"])


def test_a_symbol_with_no_overlap_is_dropped_and_reported(monkeypatch):
    install(
        monkeypatch,
        {
            "AAPL": frame(rising(60), start="2026-01-05"),
            "MSFT": frame(rising(60), start="2026-01-05"),
            "OLD": frame(rising(60), start="2019-01-07"),
        },
    )
    out = comparison.compare_symbols(["AAPL", "MSFT", "OLD"])
    assert [r["symbol"] for r in out["symbols"]] == ["AAPL", "MSFT"]
    assert [u["symbol"] for u in out["unavailable"]] == ["OLD"]
    assert "overlapping" in out["unavailable"][0]["reason"]


def test_an_unresolvable_symbol_does_not_blank_the_comparison(monkeypatch):
    install(
        monkeypatch,
        {"AAPL": frame(rising()), "MSFT": frame(rising())},
        missing={"ZZZZ"},
    )
    out = comparison.compare_symbols(["AAPL", "MSFT", "ZZZZ"])
    assert [r["symbol"] for r in out["symbols"]] == ["AAPL", "MSFT"]
    assert out["unavailable"][0]["symbol"] == "ZZZZ"


def test_too_many_failures_raises_rather_than_returning_one_line(monkeypatch):
    install(monkeypatch, {"AAPL": frame(rising())}, missing={"ZZZZ", "YYYY"})
    with pytest.raises(MarketDataError, match="Not enough symbols"):
        comparison.compare_symbols(["AAPL", "ZZZZ", "YYYY"])


# -------------------------------------------------------------- correlation


def test_the_correlation_matrix_is_square_and_symmetric(monkeypatch):
    install(
        monkeypatch,
        {"A": frame(rising(60, 0.01)), "B": frame(rising(60, 0.004)), "C": frame(rising(60, 0.02))},
    )
    matrix = comparison.compare_symbols(["A", "B", "C"])["correlations"]
    assert matrix["symbols"] == ["A", "B", "C"]
    assert len(matrix["values"]) == 3
    for i in range(3):
        assert matrix["values"][i][i] == pytest.approx(1.0)
        for j in range(3):
            assert matrix["values"][i][j] == pytest.approx(matrix["values"][j][i])


def test_opposing_series_correlate_negatively(monkeypatch):
    rng = np.random.default_rng(3)
    steps = rng.normal(0.001, 0.02, 80)
    up = 100 * np.cumprod(1 + steps)
    down = 100 * np.cumprod(1 - steps)
    install(monkeypatch, {"UP": frame(up), "DOWN": frame(down)})
    out = comparison.compare_symbols(["UP", "DOWN"])
    assert out["symbols"][1]["metrics"]["correlation_vs_benchmark"] < -0.9


# -------------------------------------------------------------- narration


def test_the_explanation_names_the_leader_and_the_laggard(monkeypatch):
    install(monkeypatch, {"WIN": frame(rising(60, 0.02)), "LOSE": frame(rising(60, -0.01))})
    out = comparison.compare_symbols(["WIN", "LOSE"])
    body = " ".join(p["body"] for p in comparison.explain_comparison(out))
    assert "WIN returned" in body
    assert "LOSE" in body


def test_the_explanation_flags_tightly_correlated_pairs(monkeypatch):
    series = rising(60)
    install(monkeypatch, {"A": frame(series), "B": frame(series * 1.5)})
    out = comparison.compare_symbols(["A", "B"])
    body = " ".join(p["body"] for p in comparison.explain_comparison(out))
    assert "move together closely" in body


def test_the_explanation_mentions_dropped_symbols(monkeypatch):
    install(monkeypatch, {"AAPL": frame(rising()), "MSFT": frame(rising())}, missing={"ZZZZ"})
    out = comparison.compare_symbols(["AAPL", "MSFT", "ZZZZ"])
    body = " ".join(p["body"] for p in comparison.explain_comparison(out))
    assert "ZZZZ" in body


def test_the_explanation_refuses_to_read_as_advice(monkeypatch):
    install(monkeypatch, {"WIN": frame(rising(60, 0.02)), "LOSE": frame(rising(60, -0.01))})
    out = comparison.compare_symbols(["WIN", "LOSE"])
    body = " ".join(p["body"] for p in comparison.explain_comparison(out))
    assert "not evidence of anything repeatable" in body
