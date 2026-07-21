"""P2.2: DocumentRepository — user-scoped CRUD + status transitions."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base, build_engine, build_session_factory
from app.db.repositories import DocumentRepository, UserRepository


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


def _user_id(session: Session) -> str:
    user = UserRepository(session).create(email="alice@example.com", password_hash="h")
    session.commit()
    return user.id


def test_create_and_get(session: Session) -> None:
    user_id = _user_id(session)
    repo = DocumentRepository(session)
    doc = repo.create(user_id=user_id, filename="10k.pdf", storage_key=f"{user_id}/x.pdf", page_count=42)
    session.commit()

    fetched = repo.get(document_id=doc.id, user_id=user_id)
    assert fetched is not None
    assert fetched.filename == "10k.pdf"
    assert fetched.page_count == 42
    assert fetched.status == "queued"
    assert fetched.stage is None


def test_get_scoped_to_owner(session: Session) -> None:
    user_id = _user_id(session)
    other_id = UserRepository(session).create(email="bob@example.com", password_hash="h").id
    session.commit()

    repo = DocumentRepository(session)
    doc = repo.create(user_id=user_id, filename="10k.pdf", storage_key="x")
    session.commit()

    assert repo.get(document_id=doc.id, user_id=other_id) is None
    assert repo.get(document_id=doc.id, user_id=user_id) is not None


def test_list_for_user_orders_newest_first(session: Session) -> None:
    user_id = _user_id(session)
    repo = DocumentRepository(session)
    first = repo.create(user_id=user_id, filename="a.pdf", storage_key="a")
    second = repo.create(user_id=user_id, filename="b.pdf", storage_key="b")
    session.commit()

    docs = repo.list_for_user(user_id=user_id)
    assert [d.id for d in docs] == [second.id, first.id]


def test_count_for_user(session: Session) -> None:
    user_id = _user_id(session)
    repo = DocumentRepository(session)
    assert repo.count_for_user(user_id=user_id) == 0
    repo.create(user_id=user_id, filename="a.pdf", storage_key="a")
    repo.create(user_id=user_id, filename="b.pdf", storage_key="b")
    session.commit()
    assert repo.count_for_user(user_id=user_id) == 2


def test_update_status(session: Session) -> None:
    user_id = _user_id(session)
    repo = DocumentRepository(session)
    doc = repo.create(user_id=user_id, filename="a.pdf", storage_key="a")
    session.commit()

    repo.update_status(document_id=doc.id, user_id=user_id, status="processing", stage="detect")
    session.commit()

    fetched = repo.get(document_id=doc.id, user_id=user_id)
    assert fetched is not None
    assert fetched.status == "processing"
    assert fetched.stage == "detect"


def test_update_status_wrong_owner_is_noop(session: Session) -> None:
    user_id = _user_id(session)
    other_id = UserRepository(session).create(email="carol@example.com", password_hash="h").id
    session.commit()

    repo = DocumentRepository(session)
    doc = repo.create(user_id=user_id, filename="a.pdf", storage_key="a")
    session.commit()

    repo.update_status(document_id=doc.id, user_id=other_id, status="failed", error="hijacked")
    session.commit()

    fetched = repo.get(document_id=doc.id, user_id=user_id)
    assert fetched is not None
    assert fetched.status == "queued"  # unchanged
