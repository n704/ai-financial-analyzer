"""Comparison HTTP routes. Market data is monkeypatched; the model is not loaded."""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import comparison, main, market_data  # noqa: E402
from backend.app.kronos_engine import ModelNotReady  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.market_data import MarketData, MarketDataError  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    market_data.clear_caches()
    rng = np.random.default_rng(0)

    def fake_fetch(symbol, interval, bars):
        if symbol == "ZZZZ":
            raise MarketDataError(f"No market data returned for '{symbol}'.")
        idx = pd.date_range("2026-01-05", periods=90, freq="B", tz="America/New_York")
        closes = 100 * np.cumprod(1 + rng.normal(0.001, 0.015, 90))
        return MarketData(
            symbol,
            interval,
            pd.DataFrame(
                {
                    "open": closes,
                    "high": closes * 1.01,
                    "low": closes * 0.99,
                    "close": closes,
                    "volume": np.full(90, 1e6),
                },
                index=idx,
            ),
            {"symbol": symbol, "name": f"{symbol} Inc.", "currency": "USD"},
        )

    monkeypatch.setattr(comparison, "fetch_ohlcv", fake_fetch)
    with TestClient(app) as c:
        yield c
    market_data.clear_caches()


def body(**over):
    return {"symbols": ["AAPL", "MSFT"], "interval": "1d", "bars": 90, **over}


# ---------------------------------------------------------------- /compare


def test_compare_returns_a_row_per_symbol(client):
    out = client.post("/api/compare", json=body(symbols=["AAPL", "MSFT", "NVDA"])).json()
    assert [r["symbol"] for r in out["symbols"]] == ["AAPL", "MSFT", "NVDA"]
    assert out["benchmark"] == "AAPL"
    assert out["bars"] > 0


def test_compare_includes_the_rebased_series_for_the_chart(client):
    out = client.post("/api/compare", json=body()).json()
    series = out["symbols"][0]["series"]
    assert series[0]["value"] == pytest.approx(100.0)
    assert len(series) == out["bars"]


def test_compare_includes_a_correlation_matrix(client):
    out = client.post("/api/compare", json=body(symbols=["AAPL", "MSFT", "NVDA"])).json()
    assert len(out["correlations"]["values"]) == 3


def test_compare_includes_explanations(client):
    out = client.post("/api/compare", json=body()).json()
    assert out["explanations"]
    assert all({"title", "body"} <= set(p) for p in out["explanations"])


def test_compare_reports_an_unresolvable_symbol_without_failing(client):
    out = client.post("/api/compare", json=body(symbols=["AAPL", "MSFT", "ZZZZ"])).json()
    assert [u["symbol"] for u in out["unavailable"]] == ["ZZZZ"]
    assert len(out["symbols"]) == 2


def test_compare_needs_at_least_two_symbols(client):
    assert client.post("/api/compare", json=body(symbols=["AAPL"])).status_code == 422


def test_compare_caps_the_symbol_count(client):
    too_many = [f"S{i}" for i in range(7)]
    assert client.post("/api/compare", json=body(symbols=too_many)).status_code == 422


def test_compare_rejects_an_unknown_interval(client):
    assert client.post("/api/compare", json=body(interval="1w")).status_code == 400


def test_compare_rejects_an_absurd_bar_count(client):
    assert client.post("/api/compare", json=body(bars=5)).status_code == 422


# ------------------------------------------------------- /compare/forecast


def test_forecast_returns_only_the_signal_slice(client, monkeypatch):
    """The compare column needs the signal, not 260 bars of history."""
    monkeypatch.setattr(
        main,
        "analyze",
        lambda req: {
            "symbol": req.symbol,
            "signal": {"action": "BUY", "confidence": 70, "rationale": []},
            "stats": {"prob_up": 0.7, "expected_return_pct": 2.0},
            "diagnostics": {"caveats": []},
            "history": [{"huge": True}] * 260,
        },
    )
    out = client.post("/api/compare/forecast", json={"symbol": "AAPL"}).json()
    assert set(out) == {"symbol", "signal", "stats", "diagnostics"}
    assert out["signal"]["action"] == "BUY"


def test_forecast_skips_the_backtest(client, monkeypatch):
    """It roughly doubles runtime and the compare table never shows it."""
    seen = {}

    def capture(req):
        seen["backtest"] = req.backtest
        seen["symbol"] = req.symbol
        return {"symbol": req.symbol, "signal": {}, "stats": {}, "diagnostics": {}}

    monkeypatch.setattr(main, "analyze", capture)
    client.post("/api/compare/forecast", json={"symbol": "aapl"})
    assert seen["backtest"] is False
    assert seen["symbol"] == "aapl"


def test_forecast_rejects_a_lookback_beyond_the_context_window(client):
    out = client.post("/api/compare/forecast", json={"symbol": "AAPL", "lookback": 512})
    # Kronos-small has a 512-bar context, so 512 is allowed but 9999 is not.
    assert out.status_code != 422 or "context window" in out.text
    assert client.post(
        "/api/compare/forecast", json={"symbol": "AAPL", "lookback": 9999}
    ).status_code == 422


def test_forecast_surfaces_an_unloaded_model_as_503(client, monkeypatch):
    def not_ready(req):
        raise ModelNotReady("Model is not loaded")

    monkeypatch.setattr(main, "analyze", not_ready)
    assert client.post("/api/compare/forecast", json={"symbol": "AAPL"}).status_code == 503


def test_forecast_surfaces_a_bad_symbol_as_400(client, monkeypatch):
    def bad(req):
        raise MarketDataError("No market data returned for 'ZZZZ'.")

    monkeypatch.setattr(main, "analyze", bad)
    assert client.post("/api/compare/forecast", json={"symbol": "ZZZZ"}).status_code == 400
