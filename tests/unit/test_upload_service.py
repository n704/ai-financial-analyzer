"""P2.2: the ``upload_document`` service — validation, quota, storage, DB
insert, and enqueue, wired together against real (in-memory/temp) infra."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, build_engine, build_session_factory
from app.db.repositories import DocumentRepository, UserRepository
from app.domain.validation import NotAPdf, PdfTooManyPages
from app.infra.events import InProcessEventBus
from app.infra.queue import InProcessQueue
from app.services.documents import QuotaExceeded, UploadLimits, upload_document
from app.services.jobs import INGEST_DOCUMENT_JOB, JobContext, document_channel, run_ingest_document
from app.storage.local import LocalObjectStorage


def _make_pdf(pages: int = 1) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def queue(session_factory: sessionmaker[Session]) -> InProcessQueue:
    q = InProcessQueue()
    job_ctx = JobContext(session_factory=session_factory, events=InProcessEventBus())
    q.register(INGEST_DOCUMENT_JOB, functools.partial(run_ingest_document, job_ctx))
    return q


def _limits(**overrides: int) -> UploadLimits:
    base: dict[str, int] = {"max_upload_mb": 30, "max_pages": 600, "default_document_quota": 100}
    base.update(overrides)
    return UploadLimits(**base)


async def test_upload_success_lands_in_storage_db_and_queue(
    tmp_path: Path,
    session: Session,
    session_factory: sessionmaker[Session],
    queue: InProcessQueue,
) -> None:
    user = UserRepository(session).create(email="alice@example.com", password_hash="h")
    session.commit()
    storage = LocalObjectStorage(root=str(tmp_path), signing_secret="secret")

    document = await upload_document(
        user=user,
        filename="10k.pdf",
        data=_make_pdf(3),
        session=session,
        storage=storage,
        queue=queue,
        limits=_limits(),
    )

    assert document.status == "queued"
    assert document.page_count == 3
    assert document.storage_key == f"{user.id}/{document.id}.pdf"
    assert storage.exists(document.storage_key)

    await asyncio.sleep(0.01)  # let the enqueued in-process job run

    # A fresh session (as a real second HTTP request would use) rather than
    # the one still holding `document` in its identity map from the insert
    # above — `expire_on_commit=False` means that session's cached copy
    # wouldn't reflect the job's update even though the DB row changed.
    with session_factory() as fresh_session:
        refreshed = DocumentRepository(fresh_session).get(document_id=document.id, user_id=user.id)
        assert refreshed is not None
        assert refreshed.status == "ready"


async def test_upload_rejects_non_pdf_without_touching_storage_or_db(
    tmp_path: Path, session: Session, queue: InProcessQueue
) -> None:
    user = UserRepository(session).create(email="bob@example.com", password_hash="h")
    session.commit()
    storage = LocalObjectStorage(root=str(tmp_path), signing_secret="secret")

    with pytest.raises(NotAPdf):
        await upload_document(
            user=user,
            filename="fake.pdf",
            data=b"not a pdf",
            session=session,
            storage=storage,
            queue=queue,
            limits=_limits(),
        )

    assert DocumentRepository(session).count_for_user(user_id=user.id) == 0


async def test_upload_rejects_too_many_pages(
    tmp_path: Path, session: Session, queue: InProcessQueue
) -> None:
    user = UserRepository(session).create(email="carol@example.com", password_hash="h")
    session.commit()
    storage = LocalObjectStorage(root=str(tmp_path), signing_secret="secret")

    with pytest.raises(PdfTooManyPages):
        await upload_document(
            user=user,
            filename="big.pdf",
            data=_make_pdf(5),
            session=session,
            storage=storage,
            queue=queue,
            limits=_limits(max_pages=3),
        )


async def test_upload_enforces_document_quota(
    tmp_path: Path, session: Session, queue: InProcessQueue
) -> None:
    user = UserRepository(session).create(email="dave@example.com", password_hash="h")
    session.commit()
    storage = LocalObjectStorage(root=str(tmp_path), signing_secret="secret")
    limits = _limits(default_document_quota=1)

    await upload_document(
        user=user, filename="a.pdf", data=_make_pdf(1), session=session,
        storage=storage, queue=queue, limits=limits,
    )

    with pytest.raises(QuotaExceeded):
        await upload_document(
            user=user, filename="b.pdf", data=_make_pdf(1), session=session,
            storage=storage, queue=queue, limits=limits,
        )


async def test_upload_respects_per_user_quota_override(
    tmp_path: Path, session: Session, queue: InProcessQueue
) -> None:
    user = UserRepository(session).create(email="erin@example.com", password_hash="h")
    user.quota_documents = 0
    session.commit()
    storage = LocalObjectStorage(root=str(tmp_path), signing_secret="secret")

    with pytest.raises(QuotaExceeded):
        await upload_document(
            user=user, filename="a.pdf", data=_make_pdf(1), session=session,
            storage=storage, queue=queue, limits=_limits(default_document_quota=100),
        )


def test_document_channel_naming() -> None:
    assert document_channel("abc") == "document:abc"
