"""P1.8: DB layer — SQLite schema creation + user-scoped repository behavior.

Uses ``Base.metadata.create_all`` against an in-memory SQLite DB rather than
running Alembic, so these stay fast unit tests; the Alembic upgrade/downgrade
cycle itself is exercised by ``test_migrations.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base, build_engine, build_session_factory, utcnow
from app.db.repositories import IndexMetaRepository, RefreshTokenRepository, UserRepository
from app.db.repositories.users import UserAlreadyExists


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


def test_user_create_and_lookup_normalizes_email(session: Session) -> None:
    repo = UserRepository(session)
    user = repo.create(email="  Alice@Example.com ", password_hash="hash")
    session.commit()

    assert user.email == "alice@example.com"
    assert repo.get_by_email("ALICE@example.com") is not None
    assert repo.get_by_id(user.id) is not None


def test_user_create_duplicate_email_rejected(session: Session) -> None:
    repo = UserRepository(session)
    repo.create(email="bob@example.com", password_hash="h1")
    session.commit()

    with pytest.raises(UserAlreadyExists):
        repo.create(email="Bob@Example.com", password_hash="h2")


def test_user_delete_cascades_refresh_tokens(session: Session) -> None:
    users = UserRepository(session)
    tokens = RefreshTokenRepository(session)
    user = users.create(email="carol@example.com", password_hash="h")
    session.commit()

    tokens.create(user_id=user.id, token_hash="t1", expires_at=utcnow() + timedelta(days=1))
    session.commit()

    users.delete(user.id)
    session.commit()

    assert users.get_by_id(user.id) is None
    assert tokens.get_valid(user_id=user.id, token_hash="t1") is None


def test_refresh_token_rotation_and_revocation(session: Session) -> None:
    users = UserRepository(session)
    tokens = RefreshTokenRepository(session)
    user = users.create(email="dave@example.com", password_hash="h")
    session.commit()

    tokens.create(user_id=user.id, token_hash="hash-1", expires_at=utcnow() + timedelta(days=1))
    session.commit()
    assert tokens.get_valid(user_id=user.id, token_hash="hash-1") is not None

    tokens.revoke(user_id=user.id, token_hash="hash-1")
    session.commit()
    assert tokens.get_valid(user_id=user.id, token_hash="hash-1") is None


def test_refresh_token_expired_is_invalid(session: Session) -> None:
    users = UserRepository(session)
    tokens = RefreshTokenRepository(session)
    user = users.create(email="erin@example.com", password_hash="h")
    session.commit()

    tokens.create(user_id=user.id, token_hash="expired", expires_at=utcnow() - timedelta(days=1))
    session.commit()

    assert tokens.get_valid(user_id=user.id, token_hash="expired") is None


def test_refresh_token_scoped_to_owner(session: Session) -> None:
    users = UserRepository(session)
    tokens = RefreshTokenRepository(session)
    alice = users.create(email="alice2@example.com", password_hash="h")
    bob = users.create(email="bob2@example.com", password_hash="h")
    session.commit()

    tokens.create(user_id=alice.id, token_hash="shared", expires_at=utcnow() + timedelta(days=1))
    session.commit()

    # Same token_hash string, wrong owner -> must not validate.
    assert tokens.get_valid(user_id=bob.id, token_hash="shared") is None
    assert tokens.get_valid(user_id=alice.id, token_hash="shared") is not None


def test_revoke_all_for_user(session: Session) -> None:
    users = UserRepository(session)
    tokens = RefreshTokenRepository(session)
    user = users.create(email="frank@example.com", password_hash="h")
    session.commit()
    tokens.create(user_id=user.id, token_hash="a", expires_at=utcnow() + timedelta(days=1))
    tokens.create(user_id=user.id, token_hash="b", expires_at=utcnow() + timedelta(days=1))
    session.commit()

    tokens.revoke_all_for_user(user.id)
    session.commit()

    assert tokens.get_valid(user_id=user.id, token_hash="a") is None
    assert tokens.get_valid(user_id=user.id, token_hash="b") is None


def test_index_meta_set_then_get_updates_single_row(session: Session) -> None:
    repo = IndexMetaRepository(session)
    assert repo.get() is None

    repo.set(embedding_provider="gemini", embedding_model="gemini-embedding-001", dimension=3072)
    session.commit()
    row = repo.get()
    assert row is not None
    assert row.dimension == 3072

    repo.set(embedding_provider="fake", embedding_model="fake-embedding", dimension=16)
    session.commit()
    row2 = repo.get()
    assert row2 is not None
    assert row2.embedding_provider == "fake"
    assert row2.dimension == 16
