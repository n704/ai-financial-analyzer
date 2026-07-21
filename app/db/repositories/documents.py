"""Document repository — user-scoped CRUD over the ``documents`` table (P2.2).

Every method takes and filters on ``user_id``, including ``update_status``:
there is no path that mutates a document without confirming the caller owns it
(ARCHITECTURE.md §6).
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.base import new_uuid, utcnow
from app.db.models import Document
from app.db.repositories.base import ScopedRepository


class DocumentRepository(ScopedRepository):
    def create(
        self,
        *,
        user_id: str,
        filename: str,
        storage_key: str,
        page_count: int | None = None,
        document_id: str | None = None,
    ) -> Document:
        document = Document(
            id=document_id or new_uuid(),
            user_id=user_id,
            filename=filename,
            storage_key=storage_key,
            page_count=page_count,
            status="queued",
            stage=None,
            created_at=utcnow(),
        )
        self.session.add(document)
        self.session.flush()
        return document

    def get(self, *, document_id: str, user_id: str) -> Document | None:
        stmt = select(Document).where(Document.id == document_id, Document.user_id == user_id)
        return self.session.scalar(stmt)

    def list_for_user(self, *, user_id: str, limit: int = 50, offset: int = 0) -> list[Document]:
        stmt = (
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt))

    def count_for_user(self, *, user_id: str) -> int:
        stmt = select(func.count()).select_from(Document).where(Document.user_id == user_id)
        return int(self.session.scalar(stmt) or 0)

    def update_status(
        self,
        *,
        document_id: str,
        user_id: str,
        status: str,
        stage: str | None = None,
        error: str | None = None,
    ) -> None:
        document = self.get(document_id=document_id, user_id=user_id)
        if document is not None:
            document.status = status
            document.stage = stage
            document.error = error
            self.session.flush()
