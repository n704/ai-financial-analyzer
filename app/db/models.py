"""SQLAlchemy ORM models (ARCHITECTURE.md §5), portable across SQLite (default)
and Postgres (scaled profile) — every column type here produces valid DDL on
both engines; nothing here imports a vendor driver directly.

Portability decisions vs. the "canonical" (Postgres-flavored) schema in
ARCHITECTURE.md §5:

- ``uuid`` primary keys -> ``String(36)`` (SQLite has no native UUID type).
- ``citext`` (case-insensitive email) -> a plain unique ``String``; callers
  normalize to lowercase before writing/reading (see ``UserRepository``), so
  the *contract* (case-insensitive uniqueness) holds without dialect-specific
  collation syntax in the model.
- ``jsonb`` / ``uuid[]`` -> ``JSON`` (SQLAlchemy's generic type maps to each
  dialect's native JSON support).
- ``vector(D)`` -> omitted entirely here. It exists only when
  ``vector_store.provider = pgvector``, and even then lives behind the
  ``VectorStore`` adapter (``app/providers/vectorstores/pgvector.py``), never
  as a column on this ORM model — ``chunks.text`` stays canonical either way.
- Enum-shaped columns (``status``, ``report_type``, ...) are plain ``String``,
  not ``sqlalchemy.Enum``: a native Postgres ENUM type requires ``ALTER TYPE``
  to add a value later, which fights rolling migrations. Validity is enforced
  at the Pydantic layer (``app/domain/schemas.py``, P2), not the DB schema.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_uuid, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    quota_documents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_uploads_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_questions_day: Mapped[int | None] = mapped_column(Integer, nullable=True)

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    provider_file_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (Index("ix_documents_user_created", "user_id", "created_at"),)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class IndexMeta(Base):
    """Single-row table recording the embedding space the vector store was built
    with. The startup guard (``app/providers/factory.py``) compares this against
    the configured embedding provider/model/dimension and hard-errors on
    mismatch — vectors from different models are never silently mixed
    (ARCHITECTURE.md §3, "Embedding-space guard")."""

    __tablename__ = "index_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    embedding_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    result: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)


class Usage(Base):
    __tablename__ = "usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_estimate: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (Index("ix_usage_user_created", "user_id", "created_at"),)
