"""P2.1/P2.2: the documents API through real HTTP — upload validation, storage
+ DB + queue wiring, ownership scoping, and the SSE progress stream. Uses
``config/test.yaml`` (fake LLM/embeddings, SQLite, in-memory backends).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_TEST_DATA_DIR = Path("data/test_documents")


def _make_pdf(pages: int = 2) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
    monkeypatch.setenv("APP_CONFIG", "config/test_documents.yaml")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-value-long-enough-for-hs256")
    monkeypatch.setenv("OBJECT_STORAGE_SIGNING_SECRET", "test-signing-secret-value")
    with TestClient(create_app()) as test_client:
        yield test_client
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


def _auth_headers(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2222"})
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_upload_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/documents", files={"file": ("a.pdf", _make_pdf(), "application/pdf")})
    assert resp.status_code == 401


def test_upload_rejects_non_pdf(client: TestClient) -> None:
    headers = _auth_headers(client, "alice@example.com")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", b"not a pdf", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422


def test_upload_success_returns_202_queued(client: TestClient) -> None:
    headers = _auth_headers(client, "bob@example.com")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("10k.pdf", _make_pdf(3), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["filename"] == "10k.pdf"
    assert body["page_count"] == 3
    assert body["id"]


def test_get_document_detail_reaches_ready(client: TestClient) -> None:
    headers = _auth_headers(client, "carol@example.com")
    upload_resp = client.post(
        "/api/v1/documents",
        files={"file": ("10k.pdf", _make_pdf(1), "application/pdf")},
        headers=headers,
    )
    doc_id = upload_resp.json()["id"]

    # The in-process placeholder job (P2.1) runs on the app's own event loop;
    # poll briefly rather than assume a fixed delay is enough.
    import time

    for _ in range(50):
        detail = client.get(f"/api/v1/documents/{doc_id}", headers=headers)
        assert detail.status_code == 200
        if detail.json()["status"] == "ready":
            break
        time.sleep(0.01)
    else:
        pytest.fail("document never reached status=ready")


def test_get_document_not_found_for_other_user(client: TestClient) -> None:
    headers_a = _auth_headers(client, "dave@example.com")
    headers_b = _auth_headers(client, "erin@example.com")
    upload_resp = client.post(
        "/api/v1/documents",
        files={"file": ("10k.pdf", _make_pdf(1), "application/pdf")},
        headers=headers_a,
    )
    doc_id = upload_resp.json()["id"]

    resp = client.get(f"/api/v1/documents/{doc_id}", headers=headers_b)
    assert resp.status_code == 404


def test_document_events_unknown_id_returns_404(client: TestClient) -> None:
    headers = _auth_headers(client, "frank@example.com")
    resp = client.get("/api/v1/documents/does-not-exist/events", headers=headers)
    assert resp.status_code == 404


def test_document_events_streams_progress_to_ready(client: TestClient) -> None:
    headers = _auth_headers(client, "grace@example.com")
    upload_resp = client.post(
        "/api/v1/documents",
        files={"file": ("10k.pdf", _make_pdf(1), "application/pdf")},
        headers=headers,
    )
    doc_id = upload_resp.json()["id"]

    events: list[dict[str, object]] = []
    with client.stream("GET", f"/api/v1/documents/{doc_id}/events", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            events.append(json.loads(line[len("data: ") :]))
            if events[-1].get("status") == "ready":
                break

    statuses = [e["status"] for e in events]
    assert statuses[-1] == "ready"
    # Every status the client saw is one of the pipeline's real states —
    # nothing invented, no duplicate terminal frames.
    assert set(statuses) <= {"queued", "processing", "ready"}
