"""Sector comparison: ETF mapping, relative metrics and the fallback path."""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import comparison, market_data, sectors  # noqa: E402
from backend.app.market_data import MarketData, MarketDataError  # noqa: E402

from test_comparison import frame, rising  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    market_data.clear_caches()
    yield
    market_data.clear_caches()


def install(monkeypatch, series: dict, sector=None, missing=()):
    """Fixed price frames plus a fixed sector for the primary symbol."""

    def fake_fetch(symbol, interval, bars):
        if symbol in missing:
            raise MarketDataError(f"No market data returned for '{symbol}'.")
        return MarketData(
            symbol, interval, series[symbol], {"symbol": symbol, "name": f"{symbol} Inc."}
        )

    monkeypatch.setattr(comparison, "fetch_ohlcv", fake_fetch)
    monkeypatch.setattr(
        sectors, "warm_meta", lambda s: {"symbol": s, "name": s, "sector": sector}
    )
    monkeypatch.setattr(sectors, "cached_meta", lambda s: None)


# ------------------------------------------------------------------ mapping


def test_every_yfinance_sector_maps_to_an_etf():
    for sector, etf in sectors.SECTOR_ETF.items():
        assert etf in sectors.ETF_NAMES, sector


def test_the_etf_map_has_all_eleven_sectors():
    assert len(sectors.SECTOR_ETF) == 11
    assert len(set(sectors.SECTOR_ETF.values())) == 11


def test_a_known_sector_resolves_to_its_etf(monkeypatch):
    monkeypatch.setattr(sectors, "cached_meta", lambda s: {"sector": "Technology"})
    assert sectors.resolve_sector("AAPL") == ("Technology", "XLK")


def test_an_unknown_sector_resolves_to_nothing(monkeypatch):
    monkeypatch.setattr(sectors, "cached_meta", lambda s: {"sector": "Shipping Conglomerates"})
    assert sectors.resolve_sector("XYZ") == ("Shipping Conglomerates", None)


def test_a_missing_sector_does_not_raise(monkeypatch):
    monkeypatch.setattr(sectors, "cached_meta", lambda s: {"sector": None})
    assert sectors.resolve_sector("BTC-USD") == (None, None)


def test_a_sector_etf_is_not_compared_against_itself(monkeypatch):
    """XLK vs XLK would be a flat line and a beta of exactly 1."""
    assert sectors.resolve_sector("XLK") == (None, None)
    assert sectors.resolve_sector("SPY") == (None, None)


def test_a_metadata_failure_falls_back_instead_of_erroring(monkeypatch):
    monkeypatch.setattr(sectors, "cached_meta", lambda s: None)

    def boom(symbol):
        raise RuntimeError("yahoo is down")

    monkeypatch.setattr(sectors, "warm_meta", boom)
    assert sectors.resolve_sector("AAPL") == (None, None)


def test_the_cache_is_preferred_over_a_fetch(monkeypatch):
    monkeypatch.setattr(sectors, "cached_meta", lambda s: {"sector": "Energy"})

    def explode(symbol):
        raise AssertionError("should not refetch when cached")

    monkeypatch.setattr(sectors, "warm_meta", explode)
    assert sectors.resolve_sector("XOM") == ("Energy", "XLE")


# --------------------------------------------------------------- comparison


def test_a_tech_stock_is_compared_against_xlk_and_spy(monkeypatch):
    install(
        monkeypatch,
        {"AAPL": frame(rising(90, seed=1)), "XLK": frame(rising(90, seed=2)), "SPY": frame(rising(90, seed=3))},
        sector="Technology",
    )
    out = sectors.sector_comparison("AAPL")
    assert out["sector"] == "Technology"
    assert out["sector_etf"] == "XLK"
    assert out["sector_etf_name"] == "Technology Select Sector SPDR"
    assert out["benchmark"] == "XLK"
    assert {r["symbol"] for r in out["symbols"]} == {"AAPL", "XLK", "SPY"}
    assert out["caveat"] is None


def test_a_sectorless_symbol_falls_back_to_the_market_with_a_caveat(monkeypatch):
    install(
        monkeypatch,
        {"BTC-USD": frame(rising(90, seed=1)), "SPY": frame(rising(90, seed=2))},
        sector=None,
    )
    out = sectors.sector_comparison("BTC-USD")
    assert out["sector_etf"] is None
    assert out["benchmark"] == "SPY"
    assert "broad market" in out["caveat"]
    assert {r["symbol"] for r in out["symbols"]} == {"BTC-USD", "SPY"}


def test_an_unmapped_sector_says_which_sector_it_saw(monkeypatch):
    install(
        monkeypatch,
        {"XYZ": frame(rising(90, seed=1)), "SPY": frame(rising(90, seed=2))},
        sector="Shipping Conglomerates",
    )
    out = sectors.sector_comparison("XYZ")
    assert "Shipping Conglomerates" in out["caveat"]


def test_the_symbol_itself_is_required_in_the_result(monkeypatch):
    install(
        monkeypatch,
        {"SPY": frame(rising(90))},
        sector=None,
        missing={"GONE"},
    )
    with pytest.raises(MarketDataError):
        sectors.sector_comparison("GONE")


def test_an_empty_symbol_is_rejected():
    with pytest.raises(MarketDataError, match="required"):
        sectors.sector_comparison("   ")


# ----------------------------------------------------------------- relative


def test_outperformance_is_measured_against_the_sector(monkeypatch):
    install(
        monkeypatch,
        {
            "AAPL": frame([100.0] * 30 + [130.0] * 30),
            "XLK": frame([100.0] * 30 + [110.0] * 30),
            "SPY": frame(rising(60)),
        },
        sector="Technology",
    )
    rel = sectors.sector_comparison("AAPL")["relative"]
    assert rel["stock_return_pct"] == pytest.approx(30.0)
    assert rel["benchmark_return_pct"] == pytest.approx(10.0)
    assert rel["excess_return_pct"] == pytest.approx(20.0)


def test_alpha_strips_out_the_part_explained_by_beta(monkeypatch):
    """A stock whose every move is exactly twice its sector's is pure
    leverage: it must show beta 2 and essentially zero alpha, however
    spectacular its raw outperformance looks."""
    base = np.log(rising(150, 0.004, seed=5))  # sector rises ~54%
    levered = np.exp(base[0] + 2 * (base - base[0]))
    install(
        monkeypatch,
        {"LEVER": frame(levered), "XLK": frame(np.exp(base)), "SPY": frame(rising(150, seed=9))},
        sector="Technology",
    )
    rel = sectors.sector_comparison("LEVER")["relative"]
    assert rel["beta"] == pytest.approx(2.0, abs=0.02)
    assert rel["alpha_pct"] == pytest.approx(0.0, abs=1.0)
    # Excess return ignores beta, so it reads as a huge win — which is the
    # whole reason alpha is reported alongside it.
    assert rel["excess_return_pct"] > 50


def test_alpha_is_computed_in_log_space_to_match_beta():
    """Regression: mixing a log-return beta with simple-return arithmetic gave
    a stock that exactly tracked its sector ~29 points of phantom alpha."""
    # +137% stock, +54% sector, beta 2 -> (1+1.37) == (1+0.54)**2, so alpha 0.
    assert sectors._alpha(137.06, 53.97, 2.0) == pytest.approx(0.0, abs=0.1)


def test_alpha_is_none_after_a_total_wipeout():
    assert sectors._alpha(-100.0, 10.0, 1.0) is None


def test_alpha_is_none_without_a_beta():
    assert sectors._alpha(10.0, 5.0, None) is None


def test_relative_strength_starts_at_100_and_tracks_outperformance(monkeypatch):
    install(
        monkeypatch,
        {
            "AAPL": frame([100.0] * 30 + [130.0] * 30),
            "XLK": frame([100.0] * 60),
            "SPY": frame(rising(60)),
        },
        sector="Technology",
    )
    rs = sectors.sector_comparison("AAPL")["relative_strength"]
    assert rs[0]["value"] == pytest.approx(100.0)
    assert rs[-1]["value"] == pytest.approx(130.0)


def test_relative_strength_is_flat_when_the_stock_matches_its_sector(monkeypatch):
    series = rising(90, seed=4)
    install(
        monkeypatch,
        {"AAPL": frame(series), "XLK": frame(series * 3), "SPY": frame(rising(90, seed=8))},
        sector="Technology",
    )
    rs = sectors.sector_comparison("AAPL")["relative_strength"]
    assert all(p["value"] == pytest.approx(100.0) for p in rs)


# --------------------------------------------------------------- narration


def test_the_explanation_names_the_sector_and_the_etf(monkeypatch):
    install(
        monkeypatch,
        {"AAPL": frame(rising(90, 0.004, seed=1)), "XLK": frame(rising(90, 0.001, seed=2)), "SPY": frame(rising(90, seed=3))},
        sector="Technology",
    )
    out = sectors.sector_comparison("AAPL")
    body = " ".join(f"{p['title']} {p['body']}" for p in sectors.explain_sector(out))
    assert "Technology" in body
    assert "XLK" in body
    assert "outperformed" in body


def test_the_explanation_calls_underperformance_by_its_name(monkeypatch):
    install(
        monkeypatch,
        {"AAPL": frame(rising(90, -0.004, seed=1)), "XLK": frame(rising(90, 0.004, seed=2)), "SPY": frame(rising(90, seed=3))},
        sector="Technology",
    )
    out = sectors.sector_comparison("AAPL")
    body = " ".join(p["title"] for p in sectors.explain_sector(out))
    assert "underperformed" in body


def test_the_explanation_warns_that_high_beta_is_not_skill(monkeypatch):
    base = np.log(rising(150, 0.002, seed=5))
    install(
        monkeypatch,
        {
            "LEVER": frame(np.exp(base[0] + 2 * (base - base[0]))),
            "XLK": frame(np.exp(base)),
            "SPY": frame(rising(150, seed=9)),
        },
        sector="Technology",
    )
    out = sectors.sector_comparison("LEVER")
    body = " ".join(p["body"] for p in sectors.explain_sector(out))
    assert "leverage, not skill" in body


def test_the_explanation_carries_the_fallback_caveat(monkeypatch):
    install(
        monkeypatch,
        {"BTC-USD": frame(rising(90, seed=1)), "SPY": frame(rising(90, seed=2))},
        sector=None,
    )
    out = sectors.sector_comparison("BTC-USD")
    body = " ".join(p["body"] for p in sectors.explain_sector(out))
    assert "broad market" in body


def test_the_explanation_describes_the_market_when_there_is_no_sector(monkeypatch):
    install(
        monkeypatch,
        {"BTC-USD": frame(rising(90, seed=1)), "SPY": frame(rising(90, seed=2))},
        sector=None,
    )
    out = sectors.sector_comparison("BTC-USD")
    body = sectors.explain_sector(out)[0]["body"]
    assert "broad market (SPY)" in body


def test_no_relative_data_means_no_explanation():
    assert sectors.explain_sector({"symbol": "AAPL", "relative": {}}) == []
