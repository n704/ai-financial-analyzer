"""Auth: password hashing, JWT/refresh-token mechanics, and the auth service
(P1.12). The FastAPI router + middleware that wire this into HTTP land in
P1.13 (``app/api/main.py`` / dependencies)."""

from __future__ import annotations

from app.api.auth.schemas import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.api.auth.service import (
    AuthError,
    AuthService,
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRefreshToken,
    TokenPair,
)

__all__ = [
    "AuthError",
    "AuthService",
    "EmailAlreadyRegistered",
    "InvalidCredentials",
    "InvalidRefreshToken",
    "LoginRequest",
    "LogoutRequest",
    "RefreshRequest",
    "RegisterRequest",
    "TokenPair",
    "TokenResponse",
]
