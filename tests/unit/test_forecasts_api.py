"""P6.6/P6.7: the forecast API through real HTTP — queue → job → full artifact
(band + scorecard + verdict + provenance + disclaimer in every response),
dedupe, quotas, readable failures, SSE progress, narration guardrails, and
cross-tenant denial on every endpoint. Uses ``config/test_forecast.yaml``
(fixture bars + the fake quantile-head provider); the disabled path uses
``config/test.yaml``."""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_DATA_DIR = Path("data/test_forecast")
_DISABLED_DATA_DIR = Path("data/test")


def _client_for(
    monkeypatch: pytest.MonkeyPatch, config: str, data_dir: Path
) -> Iterator[TestClient]:
    shutil.rmtree(data_dir, ignore_errors=True)
    monkeypatch.setenv("APP_CONFIG", config)
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-value-long-enough-for-hs256")
    monkeypatch.setenv("OBJECT_STORAGE_SIGNING_SECRET", "test-signing-secret-value")
    with TestClient(create_app()) as test_client:
        yield test_client
    shutil.rmtree(data_dir, ignore_errors=True)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from _client_for(monkeypatch, "config/test_forecast.yaml", _DATA_DIR)


@pytest.fixture
def disabled_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from _client_for(monkeypatch, "config/test.yaml", _DISABLED_DATA_DIR)


def _auth(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2222"})
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _wait_ready(client: TestClient, forecast_id: str, headers: dict[str, str]) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body: dict[str, object] = client.get(
            f"/api/v1/forecasts/{forecast_id}", headers=headers
        ).json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("forecast did not finish in time")


def test_requires_auth(client: TestClient) -> None:
    assert (
        client.post("/api/v1/forecasts", json={"ticker": "ACME", "horizon": 5}).status_code == 401
    )
    assert client.get("/api/v1/forecasts").status_code == 401


def test_disabled_deployment_says_so(disabled_client: TestClient) -> None:
    headers = _auth(disabled_client, "off@example.com")
    resp = disabled_client.post(
        "/api/v1/forecasts", json={"ticker": "ACME", "horizon": 5}, headers=headers
    )
    assert resp.status_code == 503
    assert "forecast.enabled" in resp.json()["detail"]


def test_full_artifact_end_to_end(client: TestClient) -> None:
    headers = _auth(client, "alice@example.com")
    resp = client.post("/api/v1/forecasts", json={"ticker": "acme", "horizon": 10}, headers=headers)
    assert resp.status_code == 202, resp.text
    queued = resp.json()
    assert queued["status"] == "queued" and queued["ticker"] == "ACME"
    assert queued["disclaimer"]["version"] == 1  # present even before the job runs

    body = _wait_ready(client, queued["id"], headers)
    assert body["status"] == "ready", body["error"]
    assert len(body["point"]) == 10 and len(body["median"]) == 10 and len(body["dates"]) == 10
    assert body["quantile_levels"] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    assert len(body["quantiles"]) == 9 and all(len(p) == 10 for p in body["quantiles"])
    assert body["band_source"] == "provider"
    backtest = body["backtest"]
    assert backtest["windows"] == 4 and backtest["horizon"] == 10
    assert backtest["model"]["coverage_80"] is not None
    assert {b["method"] for b in backtest["baselines"]} == {"last_value", "drift", "seasonal_naive"}
    assert body["skill"] in ("better than naive", "no better than naive")
    prov = body["provenance"]
    assert prov["provider"] == "fake" and prov["source"] == "fixture"
    assert prov["checkpoint_revision"] == "fake-rev" and prov["transform"] == "log"
    assert prov["context_end"] is not None and prov["generated_at"] is not None
    assert "not investment advice" in body["disclaimer"]["text"]

    # Dedupe: identical, fresh → the stored artifact with 200, same id.
    again = client.post(
        "/api/v1/forecasts", json={"ticker": "ACME", "horizon": 10}, headers=headers
    )
    assert again.status_code == 200 and again.json()["id"] == queued["id"]

    # List + filter.
    listed = client.get("/api/v1/forecasts", headers=headers).json()
    assert [f["id"] for f in listed] == [queued["id"]]
    assert client.get("/api/v1/forecasts?ticker=widg", headers=headers).json() == []

    # SSE snapshot on a finished forecast carries the verdict and closes.
    with client.stream("GET", f"/api/v1/forecasts/{queued['id']}/events", headers=headers) as s:
        frames = [line for line in s.iter_lines() if line.startswith("data:")]
    assert json.loads(frames[0][len("data: ") :])["status"] == "ready"
    assert "skill" in json.loads(frames[0][len("data: ") :])

    # Narration streams tokens and cites the artifact, never a page.
    with client.stream(
        "POST",
        f"/api/v1/forecasts/{queued['id']}/narrate",
        json={"focus": "margins"},
        headers=headers,
    ) as s:
        events = [
            json.loads(line[len("data: ") :]) for line in s.iter_lines() if line.startswith("data:")
        ]
    assert events[-1] == {"type": "done", "citation": f"forecast:{queued['id']}"}
    assert any(e["type"] == "token" for e in events)

    refused = client.post(
        f"/api/v1/forecasts/{queued['id']}/narrate",
        json={"focus": "should I buy?"},
        headers=headers,
    )
    assert refused.status_code == 422 and "investment advice" in refused.json()["detail"]

    assert client.delete(f"/api/v1/forecasts/{queued['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/forecasts/{queued['id']}", headers=headers).status_code == 404


def test_validation_errors(client: TestClient) -> None:
    headers = _auth(client, "val@example.com")
    assert (
        client.post(
            "/api/v1/forecasts", json={"ticker": "12", "horizon": 5}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/forecasts", json={"ticker": "ACME", "horizon": 31}, headers=headers
        ).status_code
        == 422
    )
    assert client.post("/api/v1/forecasts", json={"horizon": 5}, headers=headers).status_code == 422
    assert (
        client.post(
            "/api/v1/forecasts", json={"document_id": "nope", "horizon": 5}, headers=headers
        ).status_code
        == 404
    )


def test_unknown_ticker_fails_readably_not_500(client: TestClient) -> None:
    headers = _auth(client, "nope@example.com")
    resp = client.post("/api/v1/forecasts", json={"ticker": "NOPE", "horizon": 5}, headers=headers)
    assert resp.status_code == 202
    body = _wait_ready(client, resp.json()["id"], headers)
    assert body["status"] == "failed" and "NOPE" in str(body["error"])
    # Narrating a failed forecast is a conflict, not a crash.
    assert (
        client.post(
            f"/api/v1/forecasts/{resp.json()['id']}/narrate", json={}, headers=headers
        ).status_code
        == 409
    )


def test_daily_quota(client: TestClient) -> None:
    headers = _auth(client, "quota@example.com")
    for ticker, horizon in (("ACME", 5), ("WIDG", 5), ("ACME", 6)):
        assert (
            client.post(
                "/api/v1/forecasts", json={"ticker": ticker, "horizon": horizon}, headers=headers
            ).status_code
            == 202
        )
    resp = client.post("/api/v1/forecasts", json={"ticker": "WIDG", "horizon": 6}, headers=headers)
    assert resp.status_code == 403 and "quota" in resp.json()["detail"]


def test_cross_tenant_denial_on_every_endpoint(client: TestClient) -> None:
    alice = _auth(client, "alice2@example.com")
    bob = _auth(client, "bob2@example.com")
    created = client.post(
        "/api/v1/forecasts", json={"ticker": "ACME", "horizon": 5}, headers=alice
    ).json()
    _wait_ready(client, created["id"], alice)
    fid = created["id"]

    assert client.get(f"/api/v1/forecasts/{fid}", headers=bob).status_code == 404
    assert client.get("/api/v1/forecasts", headers=bob).json() == []
    assert client.get(f"/api/v1/forecasts/{fid}/events", headers=bob).status_code == 404
    assert client.post(f"/api/v1/forecasts/{fid}/narrate", json={}, headers=bob).status_code == 404
    assert client.delete(f"/api/v1/forecasts/{fid}", headers=bob).status_code == 404
    # Still there for its owner.
    assert client.get(f"/api/v1/forecasts/{fid}", headers=alice).status_code == 200
