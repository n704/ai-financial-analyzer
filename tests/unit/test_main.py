"""P1.13: the assembled FastAPI app — health/readiness, and the full auth
cycle through real HTTP requests. Uses ``config/test.yaml`` (fake LLM/
embeddings, SQLite, in-memory cache/queue/events) so it boots with zero API
keys and zero network calls, matching PLAN.md's P1 exit criterion ("CI green
with tests against the fake provider on SQLite + in-memory").
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_TEST_DATA_DIR = Path("data/test")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
    monkeypatch.setenv("APP_CONFIG", "config/test.yaml")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-value-long-enough-for-hs256")
    monkeypatch.setenv("OBJECT_STORAGE_SIGNING_SECRET", "test-signing-secret-value")
    with TestClient(create_app()) as test_client:
        yield test_client
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


def _register(client: TestClient, email: str, password: str = "hunter2222") -> dict[str, str]:
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_checks_db_and_vector_store(client: TestClient) -> None:
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"] == "ok"
    assert body["vector_store"] == "ok"
    assert "redis" not in body  # test profile uses in-memory backends only


def test_request_id_header_present(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert "X-Request-ID" in resp.headers


def test_unauth_request_to_protected_route_rejected(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_register_then_protected_route_and_login(client: TestClient) -> None:
    tokens = _register(client, "alice@example.com")
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    me_resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "alice@example.com"

    login_resp = client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": "hunter2222"}
    )
    assert login_resp.status_code == 200


def test_register_duplicate_email_conflict(client: TestClient) -> None:
    _register(client, "bob@example.com")
    resp = client.post(
        "/api/v1/auth/register", json={"email": "bob@example.com", "password": "different1"}
    )
    assert resp.status_code == 409


def test_login_wrong_password_rejected(client: TestClient) -> None:
    _register(client, "carol@example.com")
    resp = client.post(
        "/api/v1/auth/login", json={"email": "carol@example.com", "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_refresh_rotates_and_old_token_rejected(client: TestClient) -> None:
    tokens = _register(client, "dave@example.com")

    refresh_resp = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_resp.status_code == 200
    new_refresh_token = refresh_resp.json()["refresh_token"]
    assert new_refresh_token != tokens["refresh_token"]

    replay_resp = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay_resp.status_code == 401


def test_logout_then_refresh_rejected(client: TestClient) -> None:
    tokens = _register(client, "erin@example.com")

    logout_resp = client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert logout_resp.status_code == 204

    refresh_resp = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_resp.status_code == 401


def test_delete_account_revokes_access(client: TestClient) -> None:
    tokens = _register(client, "frank@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    delete_resp = client.delete("/api/v1/auth/account", headers=headers)
    assert delete_resp.status_code == 204

    me_resp = client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 401


@pytest.fixture
def ratelimited_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    data_dir = Path("data/test_ratelimit")
    shutil.rmtree(data_dir, ignore_errors=True)
    monkeypatch.setenv("APP_CONFIG", "config/test_ratelimit.yaml")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-value-long-enough-for-hs256")
    monkeypatch.setenv("OBJECT_STORAGE_SIGNING_SECRET", "test-signing-secret-value")
    with TestClient(create_app()) as test_client:
        yield test_client
    shutil.rmtree(data_dir, ignore_errors=True)


def test_per_ip_rate_limit_returns_429(ratelimited_client: TestClient) -> None:
    # config/test_ratelimit.yaml caps auth requests at 2/minute/IP.
    statuses = [
        ratelimited_client.post(
            "/api/v1/auth/login", json={"email": "x@example.com", "password": "wrong-password"}
        ).status_code
        for _ in range(4)
    ]
    assert 429 in statuses
