"""Document upload use case (P2.2): validate -> store -> insert -> enqueue.

Orchestration only — each step's real logic lives in its own layer: PDF
validation (``domain/validation.py``), the object-storage adapter, the
``DocumentRepository``, and the ``TaskQueue`` interface. Nothing here imports
a vendor SDK.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.base import new_uuid
from app.db.models import Document, User
from app.db.repositories import DocumentRepository
from app.domain.validation import validate_pdf
from app.infra.base import TaskQueue
from app.services.jobs import INGEST_DOCUMENT_JOB
from app.storage.base import ObjectStorage


class QuotaExceeded(Exception):
    """Raised when the user has reached their stored-document quota."""

    def __init__(self, quota: int) -> None:
        super().__init__(f"document quota ({quota}) reached")
        self.quota = quota


@dataclass(frozen=True, slots=True)
class UploadLimits:
    max_upload_mb: int
    max_pages: int
    default_document_quota: int


async def upload_document(
    *,
    user: User,
    filename: str,
    data: bytes,
    session: Session,
    storage: ObjectStorage,
    queue: TaskQueue,
    limits: UploadLimits,
) -> Document:
    """Validate, persist, and queue one PDF upload.

    Raises an :class:`~app.domain.validation.InvalidPdfError` subclass or
    :class:`QuotaExceeded` on rejection — the API layer maps each to a
    specific status code. Nothing is written to storage or the DB until
    validation passes, so a rejected upload leaves no trace.
    """
    documents = DocumentRepository(session)

    quota = (
        user.quota_documents if user.quota_documents is not None else limits.default_document_quota
    )
    if documents.count_for_user(user_id=user.id) >= quota:
        raise QuotaExceeded(quota)

    page_count = validate_pdf(
        data,
        max_size_bytes=limits.max_upload_mb * 1024 * 1024,
        max_pages=limits.max_pages,
    )

    document_id = new_uuid()
    storage_key = f"{user.id}/{document_id}.pdf"
    storage.put(storage_key, data, content_type="application/pdf")

    document = documents.create(
        document_id=document_id,
        user_id=user.id,
        filename=filename,
        storage_key=storage_key,
        page_count=page_count,
    )
    session.commit()

    await queue.enqueue(INGEST_DOCUMENT_JOB, document_id=document.id, user_id=user.id)
    return document
