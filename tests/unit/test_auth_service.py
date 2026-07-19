"""P1.12: full auth cycle — register/login/refresh/logout/delete-account —
plus the security properties that matter: refresh rotation + revocation,
hashed (never plaintext) refresh tokens, and no user-enumeration signal.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.api.auth.security import decode_access_token, hash_refresh_token
from app.api.auth.service import (
    AuthService,
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRefreshToken,
)
from app.config import AuthConfig
from app.db.base import Base, build_engine, build_session_factory


@pytest.fixture
def session() -> Iterator[Session]:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    s = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def auth_config(monkeypatch: pytest.MonkeyPatch) -> AuthConfig:
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-that-is-long-enough-for-hs256")
    return AuthConfig()


def _service(session: Session, auth_config: AuthConfig) -> AuthService:
    return AuthService(session=session, auth_config=auth_config)


def test_register_returns_usable_token_pair(session: Session, auth_config: AuthConfig) -> None:
    service = _service(session, auth_config)
    tokens = service.register(email="alice@example.com", password="hunter22")

    assert tokens.access_token
    assert tokens.refresh_token
    user_id = decode_access_token(
        tokens.access_token,
        secret="test-secret-value-that-is-long-enough-for-hs256",
        algorithm=auth_config.jwt_algorithm,
    )
    user = service.get_current_user(access_token=tokens.access_token)
    assert user.id == user_id
    assert user.email == "alice@example.com"


def test_register_duplicate_email_rejected(session: Session, auth_config: AuthConfig) -> None:
    service = _service(session, auth_config)
    service.register(email="bob@example.com", password="hunter22")
    with pytest.raises(EmailAlreadyRegistered):
        service.register(email="Bob@Example.com", password="different1")


def test_login_success(session: Session, auth_config: AuthConfig) -> None:
    service = _service(session, auth_config)
    service.register(email="carol@example.com", password="correct-horse")
    tokens = service.login(email="CAROL@example.com", password="correct-horse")
    assert tokens.access_token


def test_login_wrong_password_rejected(session: Session, auth_config: AuthConfig) -> None:
    service = _service(session, auth_config)
    service.register(email="dave@example.com", password="correct-horse")
    with pytest.raises(InvalidCredentials):
        service.login(email="dave@example.com", password="wrong-password")


def test_login_unknown_email_rejected_same_as_wrong_password(
    session: Session, auth_config: AuthConfig
) -> None:
    service = _service(session, auth_config)
    with pytest.raises(InvalidCredentials):
        service.login(email="nobody@example.com", password="whatever1")


def test_refresh_token_hash_is_never_stored_in_plaintext(
    session: Session, auth_config: AuthConfig
) -> None:
    service = _service(session, auth_config)
    tokens = service.register(email="erin@example.com", password="hunter22")

    from app.db.repositories import RefreshTokenRepository

    row = RefreshTokenRepository(session).get_by_hash(hash_refresh_token(tokens.refresh_token))
    assert row is not None
    assert row.token_hash != tokens.refresh_token


def test_refresh_rotates_and_old_token_cannot_be_reused(
    session: Session, auth_config: AuthConfig
) -> None:
    service = _service(session, auth_config)
    tokens = service.register(email="frank@example.com", password="hunter22")

    rotated = service.refresh(refresh_token=tokens.refresh_token)
    assert rotated.refresh_token != tokens.refresh_token

    # Replaying the original (now-revoked) refresh token must fail.
    with pytest.raises(InvalidRefreshToken):
        service.refresh(refresh_token=tokens.refresh_token)

    # But the newly rotated token works.
    again = service.refresh(refresh_token=rotated.refresh_token)
    assert again.access_token


def test_refresh_unknown_token_rejected(session: Session, auth_config: AuthConfig) -> None:
    service = _service(session, auth_config)
    with pytest.raises(InvalidRefreshToken):
        service.refresh(refresh_token="not-a-real-token")


def test_logout_revokes_refresh_token(session: Session, auth_config: AuthConfig) -> None:
    service = _service(session, auth_config)
    tokens = service.register(email="grace@example.com", password="hunter22")

    service.logout(refresh_token=tokens.refresh_token)

    with pytest.raises(InvalidRefreshToken):
        service.refresh(refresh_token=tokens.refresh_token)


def test_logout_unknown_token_is_idempotent_noop(session: Session, auth_config: AuthConfig) -> None:
    service = _service(session, auth_config)
    service.logout(refresh_token="never-existed")  # must not raise


def test_delete_account_revokes_access(session: Session, auth_config: AuthConfig) -> None:
    service = _service(session, auth_config)
    tokens = service.register(email="heidi@example.com", password="hunter22")
    user = service.get_current_user(access_token=tokens.access_token)

    service.delete_account(user_id=user.id)

    with pytest.raises(InvalidCredentials):
        service.get_current_user(access_token=tokens.access_token)
    with pytest.raises(InvalidRefreshToken):
        service.refresh(refresh_token=tokens.refresh_token)


def test_get_current_user_rejects_garbage_token(session: Session, auth_config: AuthConfig) -> None:
    service = _service(session, auth_config)
    with pytest.raises(InvalidCredentials):
        service.get_current_user(access_token="not-a-jwt")


def test_get_current_user_rejects_token_signed_with_wrong_secret(
    session: Session, auth_config: AuthConfig
) -> None:
    from app.api.auth.security import encode_access_token

    service = _service(session, auth_config)
    tokens = service.register(email="ivan@example.com", password="hunter22")
    user = service.get_current_user(access_token=tokens.access_token)

    forged = encode_access_token(
        user_id=user.id,
        secret="a-completely-different-secret-value-1234567890",
        algorithm=auth_config.jwt_algorithm,
        ttl_minutes=15,
    )
    with pytest.raises(InvalidCredentials):
        service.get_current_user(access_token=forged)
