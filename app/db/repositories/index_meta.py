"""IndexMeta repository — the single-row embedding-space record the startup
guard checks against the configured (provider, model, dimension) before
anything touches the vector store (ARCHITECTURE.md §3, "Embedding-space guard").
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import IndexMeta
from app.db.repositories.base import ScopedRepository


class IndexMetaRepository(ScopedRepository):
    def get(self) -> IndexMeta | None:
        return self.session.scalar(select(IndexMeta).order_by(IndexMeta.id.desc()).limit(1))

    def set(self, *, embedding_provider: str, embedding_model: str, dimension: int) -> IndexMeta:
        existing = self.get()
        if existing is not None:
            existing.embedding_provider = embedding_provider
            existing.embedding_model = embedding_model
            existing.dimension = dimension
            existing.updated_at = utcnow()
            self.session.flush()
            return existing
        row = IndexMeta(
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            dimension=dimension,
            updated_at=utcnow(),
        )
        self.session.add(row)
        self.session.flush()
        return row
