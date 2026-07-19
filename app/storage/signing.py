"""HMAC-signed, time-limited tokens for local object-storage signed URLs (P1.11).

S3 has native presigned URLs; local disk storage needs its own scheme so
"private, short-lived access only" (SPEC.md §6, "Security & privacy") holds
even with zero external services. Pure and vendor-free on purpose — easy to
unit test in isolation from any actual file I/O.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class InvalidSignedURL(Exception):
    """Raised when a signed-URL token is malformed, expired, or tampered with."""


def sign(*, key: str, ttl_s: int, secret: bytes) -> str:
    """Produce a ``payload.signature`` token embedding ``key`` and an expiry."""
    expires_at = int(time.time()) + ttl_s
    payload = json.dumps({"key": key, "exp": expires_at}, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(secret, payload_b64, hashlib.sha256).hexdigest()
    return f"{payload_b64.decode()}.{signature}"


def verify(token: str, *, secret: bytes) -> str:
    """Return the signed key if ``token`` is well-formed, unforged, and
    unexpired; otherwise raise :class:`InvalidSignedURL`."""
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError as exc:
        raise InvalidSignedURL("malformed token") from exc

    expected = hmac.new(secret, payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise InvalidSignedURL("signature mismatch")

    padding = "=" * (-len(payload_b64) % 4)
    try:
        payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidSignedURL("malformed payload") from exc

    if payload.get("exp", 0) < time.time():
        raise InvalidSignedURL("token expired")

    key = payload.get("key")
    if not isinstance(key, str):
        raise InvalidSignedURL("missing key in payload")
    return key
