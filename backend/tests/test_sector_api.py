"""The /api/sector route. Market data and metadata are monkeypatched."""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import comparison, market_data, sectors  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.market_data import MarketData, MarketDataError  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    market_data.clear_caches()
    rng = np.random.default_rng(11)

    def fake_fetch(symbol, interval, bars):
        if symbol == "ZZZZ":
            raise MarketDataError(f"No market data returned for '{symbol}'.")
        idx = pd.date_range("2026-01-05", periods=120, freq="B", tz="America/New_York")
        closes = 100 * np.cumprod(1 + rng.normal(0.001, 0.015, 120))
        return MarketData(
            symbol,
            interval,
            pd.DataFrame(
                {
                    "open": closes,
                    "high": closes * 1.01,
                    "low": closes * 0.99,
                    "close": closes,
                    "volume": np.full(120, 1e6),
                },
                index=idx,
            ),
            {"symbol": symbol, "name": f"{symbol} Inc.", "currency": "USD"},
        )

    monkeypatch.setattr(comparison, "fetch_ohlcv", fake_fetch)
    monkeypatch.setattr(sectors, "cached_meta", lambda s: {"sector": "Technology"})
    with TestClient(app) as c:
        yield c
    market_data.clear_caches()


def test_sector_route_returns_the_matched_etf(client):
    out = client.get("/api/sector/AAPL").json()
    assert out["symbol"] == "AAPL"
    assert out["sector"] == "Technology"
    assert out["sector_etf"] == "XLK"
    assert out["benchmark"] == "XLK"
    assert out["caveat"] is None


def test_sector_route_includes_all_three_series(client):
    out = client.get("/api/sector/AAPL").json()
    assert {r["symbol"] for r in out["symbols"]} == {"AAPL", "XLK", "SPY"}


def test_sector_route_includes_relative_metrics(client):
    rel = client.get("/api/sector/AAPL").json()["relative"]
    assert {"excess_return_pct", "alpha_pct", "beta", "correlation"} <= set(rel)
    assert rel["benchmark"] == "XLK"


def test_sector_route_includes_a_relative_strength_line(client):
    out = client.get("/api/sector/AAPL").json()
    assert out["relative_strength"][0]["value"] == pytest.approx(100.0)
    assert len(out["relative_strength"]) == out["bars"]


def test_sector_route_includes_explanations(client):
    out = client.get("/api/sector/AAPL").json()
    assert out["explanations"]
    assert all({"title", "body"} <= set(p) for p in out["explanations"])


def test_sector_route_falls_back_for_a_sectorless_symbol(client, monkeypatch):
    monkeypatch.setattr(sectors, "cached_meta", lambda s: {"sector": None})
    out = client.get("/api/sector/BTC-USD").json()
    assert out["sector_etf"] is None
    assert out["benchmark"] == "SPY"
    assert "broad market" in out["caveat"]


def test_sector_route_lowercases_are_normalised(client):
    assert client.get("/api/sector/aapl").json()["symbol"] == "AAPL"


def test_sector_route_reports_an_unresolvable_symbol_as_400(client):
    assert client.get("/api/sector/ZZZZ").status_code == 400


def test_sector_route_rejects_an_absurd_bar_count(client):
    assert client.get("/api/sector/AAPL", params={"bars": 5}).status_code == 422
    assert client.get("/api/sector/AAPL", params={"bars": 99999}).status_code == 422


def test_sector_route_honours_the_interval(client):
    out = client.get("/api/sector/AAPL", params={"interval": "1d", "bars": 90}).json()
    assert out["interval"] == "1d"
    assert out["interval_label"] == "Daily"
