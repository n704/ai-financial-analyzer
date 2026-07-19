"""Auth service (P1.12): register, login, refresh (rotating), logout, delete
account. Each public method is one complete unit of work — it commits the
session on success and leaves it rolled back on failure — so a request handler
just calls one method per request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.api.auth.security import (
    decode_access_token,
    dummy_password_hash,
    encode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.config import AuthConfig
from app.db.base import utcnow
from app.db.models import User
from app.db.repositories import RefreshTokenRepository, UserRepository
from app.db.repositories.users import UserAlreadyExists


class AuthError(Exception):
    """Base class for auth failures the API maps to 401/409 (ARCHITECTURE.md §6)."""


class EmailAlreadyRegistered(AuthError):
    pass


class InvalidCredentials(AuthError):
    """Wrong email or password. Deliberately doesn't say which — that would
    let an attacker enumerate registered emails."""


class InvalidRefreshToken(AuthError):
    """Refresh token is missing, expired, revoked, or forged."""


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


class AuthService:
    def __init__(self, *, session: Session, auth_config: AuthConfig) -> None:
        self._session = session
        self._config = auth_config
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)

    def register(self, *, email: str, password: str) -> TokenPair:
        try:
            user = self._users.create(email=email, password_hash=hash_password(password))
        except UserAlreadyExists as exc:
            self._session.rollback()
            raise EmailAlreadyRegistered(str(exc)) from exc
        tokens = self._issue_tokens(user.id)
        self._session.commit()
        return tokens

    def login(self, *, email: str, password: str) -> TokenPair:
        user = self._users.get_by_email(email)
        # Always run a real Argon2 comparison, even with no matching user —
        # otherwise "no such user" short-circuits before hashing runs, and the
        # timing difference lets an attacker enumerate registered emails.
        password_hash = user.password_hash if user is not None else dummy_password_hash()
        password_ok = verify_password(password, password_hash)
        if user is None or not password_ok:
            raise InvalidCredentials("invalid email or password")
        tokens = self._issue_tokens(user.id)
        self._session.commit()
        return tokens

    def refresh(self, *, refresh_token: str) -> TokenPair:
        """Validate the presented token, then rotate: revoke it and issue a
        fresh pair in the same transaction, so replaying a used refresh token
        (e.g. after theft) fails on its very next use."""
        token_hash = hash_refresh_token(refresh_token)
        row = self._tokens.get_by_hash(token_hash)
        if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
            raise InvalidRefreshToken("refresh token is invalid, expired, or already used")
        self._tokens.revoke(user_id=row.user_id, token_hash=token_hash)
        tokens = self._issue_tokens(row.user_id)
        self._session.commit()
        return tokens

    def logout(self, *, refresh_token: str) -> None:
        """Revoke one refresh token. Unknown/already-revoked tokens are a
        silent no-op — logout is idempotent from the caller's perspective."""
        token_hash = hash_refresh_token(refresh_token)
        row = self._tokens.get_by_hash(token_hash)
        if row is not None:
            self._tokens.revoke(user_id=row.user_id, token_hash=token_hash)
        self._session.commit()

    def delete_account(self, *, user_id: str) -> None:
        """Delete the user row; FK cascades remove refresh tokens (and, once
        populated, documents/analyses/conversations/usage). Object-storage and
        vector-store cleanup are separate idempotent jobs — ARCHITECTURE.md §5."""
        self._users.delete(user_id)
        self._session.commit()

    def get_current_user(self, *, access_token: str) -> User:
        """Resolve an access token to its owning :class:`User`. Raises
        :class:`InvalidCredentials` if the token is invalid or the user no
        longer exists (e.g. deleted after the token was issued)."""
        secret = self._config.resolve_secret().get_secret_value()
        try:
            user_id = decode_access_token(
                access_token, secret=secret, algorithm=self._config.jwt_algorithm
            )
        except Exception as exc:
            raise InvalidCredentials("invalid or expired access token") from exc
        user = self._users.get_by_id(user_id)
        if user is None:
            raise InvalidCredentials("invalid or expired access token")
        return user

    def _issue_tokens(self, user_id: str) -> TokenPair:
        refresh_token = new_refresh_token()
        expires_at = utcnow() + timedelta(days=self._config.refresh_ttl_days)
        self._tokens.create(
            user_id=user_id, token_hash=hash_refresh_token(refresh_token), expires_at=expires_at
        )
        access_token = encode_access_token(
            user_id=user_id,
            secret=self._config.resolve_secret().get_secret_value(),
            algorithm=self._config.jwt_algorithm,
            ttl_minutes=self._config.access_ttl_minutes,
        )
        return TokenPair(access_token=access_token, refresh_token=refresh_token)
