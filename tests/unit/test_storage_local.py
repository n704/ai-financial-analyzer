"""P1.11: local object storage — put/get/delete round-trip, path-escape
guarding, and signed-URL generation + verification. S3/MinIO is exercised in
CI's testcontainers integration job (no live MinIO in this environment)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.storage.base import ObjectNotFound
from app.storage.local import LocalObjectStorage


def _store(tmp_path: Path) -> LocalObjectStorage:
    return LocalObjectStorage(root=str(tmp_path / "objects"), signing_secret="test-secret")


def test_put_get_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put("u1/doc1.pdf", b"pdf-bytes")
    assert store.get("u1/doc1.pdf") == b"pdf-bytes"


def test_get_missing_raises_object_not_found(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ObjectNotFound):
        store.get("nope.pdf")


def test_exists(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.exists("u1/doc1.pdf") is False
    store.put("u1/doc1.pdf", b"x")
    assert store.exists("u1/doc1.pdf") is True


def test_delete_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put("u1/doc1.pdf", b"x")
    store.delete("u1/doc1.pdf")
    assert store.exists("u1/doc1.pdf") is False
    store.delete("u1/doc1.pdf")  # second delete must not raise


def test_put_creates_nested_directories(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put("a/b/c/doc.pdf", b"nested")
    assert store.get("a/b/c/doc.pdf") == b"nested"


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="escapes storage root"):
        store.put("../escape.pdf", b"x")


def test_absolute_path_traversal_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="escapes storage root"):
        store.get("/etc/passwd")


def test_signed_url_round_trips_to_original_key(tmp_path: Path) -> None:
    store = _store(tmp_path)
    url = store.signed_url("u1/doc1.pdf", ttl_s=60)
    token = url.rsplit("/", 1)[-1]
    assert store.verify_signed_token(token) == "u1/doc1.pdf"


def test_signed_url_expires(tmp_path: Path) -> None:
    from app.storage.signing import InvalidSignedURL

    store = _store(tmp_path)
    url = store.signed_url("u1/doc1.pdf", ttl_s=0)
    token = url.rsplit("/", 1)[-1]
    time.sleep(0.01)
    with pytest.raises(InvalidSignedURL, match="expired"):
        store.verify_signed_token(token)


def test_signed_url_tampered_token_rejected(tmp_path: Path) -> None:
    from app.storage.signing import InvalidSignedURL

    store = _store(tmp_path)
    url = store.signed_url("u1/doc1.pdf", ttl_s=60)
    token = url.rsplit("/", 1)[-1]
    payload_b64, signature = token.split(".", 1)
    tampered = f"{payload_b64}.{'0' * len(signature)}"
    with pytest.raises(InvalidSignedURL, match="signature mismatch"):
        store.verify_signed_token(tampered)


def test_signed_url_different_secret_rejected(tmp_path: Path) -> None:
    from app.storage.signing import InvalidSignedURL

    store_a = _store(tmp_path)
    store_b = LocalObjectStorage(root=str(tmp_path / "objects"), signing_secret="other-secret")
    url = store_a.signed_url("u1/doc1.pdf", ttl_s=60)
    token = url.rsplit("/", 1)[-1]
    with pytest.raises(InvalidSignedURL):
        store_b.verify_signed_token(token)
