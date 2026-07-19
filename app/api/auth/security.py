"""Password hashing and JWT mechanics (P1.12).

Argon2id (via ``argon2-cffi``) for password storage; PyJWT for stateless access
tokens. Refresh tokens are opaque random strings — only their SHA-256 hash is
ever persisted (see ``RefreshTokenRepository``), so a database leak alone can't
be replayed as a live session.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

# Used to keep `verify_password` at a constant cost even when no user/hash
# exists to compare against (see AuthService.login) — otherwise a missing
# user short-circuits before Argon2 runs, and the timing difference leaks
# whether an email is registered.
_DUMMY_HASH = _hasher.hash("not-a-real-password-used-only-for-constant-time-login")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def dummy_password_hash() -> str:
    """A valid Argon2id hash of a fixed, non-secret password — used so login
    always performs a real hash comparison, whether or not the account exists."""
    return _DUMMY_HASH


def new_refresh_token() -> str:
    """A high-entropy opaque token. Never stored as-is — only its hash is."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class InvalidAccessToken(Exception):
    """Raised when an access token is malformed, expired, or fails verification."""


def encode_access_token(*, user_id: str, secret: str, algorithm: str, ttl_minutes: int) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
        "type": "access",
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str, *, secret: str, algorithm: str) -> str:
    """Return the user id encoded in a valid, unexpired access token."""
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidAccessToken(str(exc)) from exc
    if payload.get("type") != "access":
        raise InvalidAccessToken("not an access token")
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise InvalidAccessToken("token is missing a subject")
    return sub
