"""Watchlist and quote HTTP routes. Storage goes to a temp DB; no network."""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import market_data, quotes, storage  # noqa: E402
from backend.app.main import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.config, "WATCHLIST_BACKEND", "sqlite")
    monkeypatch.setattr(storage.config, "WATCHLIST_DB", str(tmp_path / "test.db"))
    storage.reset_repository()
    quotes.clear_cache()
    market_data.clear_caches()
    with TestClient(app) as c:
        yield c
    storage.reset_repository()


def _frame(closes):
    idx = pd.date_range("2026-08-05", periods=len(closes), freq="B", tz="America/New_York")
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1.0] * len(closes)},
        index=idx,
    )


# ------------------------------------------------------------------- CRUD


def test_a_fresh_install_has_no_watchlists(client):
    assert client.get("/api/watchlists").json() == []


def test_create_add_read_remove_delete_round_trip(client):
    created = client.post("/api/watchlists", json={"name": "Tech"})
    assert created.status_code == 201
    wl_id = created.json()["id"]

    added = client.post(f"/api/watchlists/{wl_id}/symbols", json={"symbol": "nvda"})
    assert [i["symbol"] for i in added.json()["items"]] == ["NVDA"]

    listed = client.get("/api/watchlists").json()
    assert len(listed) == 1
    assert listed[0]["name"] == "Tech"

    removed = client.delete(f"/api/watchlists/{wl_id}/symbols/NVDA")
    assert removed.json()["items"] == []

    assert client.delete(f"/api/watchlists/{wl_id}").status_code == 204
    assert client.get("/api/watchlists").json() == []


def test_rename(client):
    wl_id = client.post("/api/watchlists", json={"name": "Tech"}).json()["id"]
    assert client.patch(f"/api/watchlists/{wl_id}", json={"name": "Megacaps"}).json()["name"] == (
        "Megacaps"
    )


def test_adding_a_symbol_twice_is_a_no_op_not_an_error(client):
    wl_id = client.post("/api/watchlists", json={"name": "Tech"}).json()["id"]
    client.post(f"/api/watchlists/{wl_id}/symbols", json={"symbol": "AAPL"})
    again = client.post(f"/api/watchlists/{wl_id}/symbols", json={"symbol": "aapl"})
    assert again.status_code == 200
    assert [i["symbol"] for i in again.json()["items"]] == ["AAPL"]


def test_a_note_survives_the_round_trip(client):
    wl_id = client.post("/api/watchlists", json={"name": "Tech"}).json()["id"]
    out = client.post(
        f"/api/watchlists/{wl_id}/symbols", json={"symbol": "AAPL", "note": "earnings 30 Oct"}
    ).json()
    assert out["items"][0]["note"] == "earnings 30 Oct"


def test_operations_on_a_missing_watchlist_are_404(client):
    assert client.get("/api/watchlists/999").status_code == 404
    assert client.patch("/api/watchlists/999", json={"name": "x"}).status_code == 404
    assert client.delete("/api/watchlists/999").status_code == 404
    assert client.post("/api/watchlists/999/symbols", json={"symbol": "AAPL"}).status_code == 404


def test_a_blank_name_is_rejected_by_validation(client):
    assert client.post("/api/watchlists", json={"name": ""}).status_code == 422


def test_a_whitespace_only_name_is_rejected_by_storage(client):
    """Passes pydantic's min_length but must not create an unnamed list."""
    assert client.post("/api/watchlists", json={"name": "   "}).status_code == 400


def test_watchlists_persist_across_app_restarts(client, tmp_path, monkeypatch):
    wl_id = client.post("/api/watchlists", json={"name": "Tech"}).json()["id"]
    client.post(f"/api/watchlists/{wl_id}/symbols", json={"symbol": "AAPL"})

    # Drop the singleton exactly as a process restart would.
    storage.reset_repository()
    with TestClient(app) as fresh:
        out = fresh.get("/api/watchlists").json()
    assert [i["symbol"] for i in out[0]["items"]] == ["AAPL"]


# ----------------------------------------------------------------- quotes


def test_quotes_endpoint_returns_a_row_per_symbol(client, monkeypatch):
    monkeypatch.setattr(quotes.yf, "download", lambda **kw: _frame([100.0, 110.0]))
    out = client.get("/api/quotes", params={"symbols": "AAPL"}).json()
    assert out[0]["symbol"] == "AAPL"
    assert out[0]["price"] == 110.0
    assert out[0]["change_pct"] == pytest.approx(10.0)


def test_quotes_endpoint_rejects_an_oversized_batch(client):
    symbols = ",".join(f"S{i}" for i in range(quotes.MAX_SYMBOLS + 1))
    assert client.get("/api/quotes", params={"symbols": symbols}).status_code == 400


def test_quotes_endpoint_requires_the_symbols_parameter(client):
    assert client.get("/api/quotes").status_code == 422


def test_a_broken_upstream_surfaces_as_502_not_500(client, monkeypatch):
    def boom(**kw):
        raise RuntimeError("yahoo is down")

    monkeypatch.setattr(quotes.yf, "download", boom)
    assert client.get("/api/quotes", params={"symbols": "AAPL"}).status_code == 502


def test_existing_endpoints_still_work(client):
    """The new routes sit above the static mount and must not shadow these."""
    assert client.get("/api/health").json()["status"] == "ok"
    assert "intervals" in client.get("/api/config").json()
