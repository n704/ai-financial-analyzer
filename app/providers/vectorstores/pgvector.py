"""pgvector vector store adapter (P1.9) — scaled profile, reuses ``database.url``.

Stores chunk embeddings in a dedicated ``chunk_embeddings`` table rather than as
a column bolted onto the Alembic-managed ``chunks`` table: the vector's width
depends on the *configured embedding model*, which a statically-typed Alembic
column can't express across every possible model choice. This adapter creates
and owns that table idempotently at construction time (``CREATE EXTENSION IF NOT
EXISTS vector`` + ``CREATE TABLE IF NOT EXISTS`` + an HNSW cosine index).
``chunks.text`` in the main schema stays canonical either way, per
ARCHITECTURE.md §5.

Requires the ``postgres`` extra (``psycopg`` + ``pgvector``); only imported when
``vector_store.provider = pgvector`` is selected (see ``app/providers/factory.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, MetaData, Select, String, Table, delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from app.providers.base import ChunkHit, ChunkRecord


class PgVectorStore:
    """Postgres + pgvector implementation of
    :class:`~app.providers.base.VectorStore`."""

    def __init__(
        self, *, engine: Engine, dimension: int, table_name: str = "chunk_embeddings"
    ) -> None:
        self._engine = engine
        self._dimension = dimension
        metadata = MetaData()
        self._table = Table(
            table_name,
            metadata,
            Column("id", String(36), primary_key=True),
            Column("document_id", String(36), nullable=False, index=True),
            Column("user_id", String(36), nullable=False, index=True),
            Column("text", String, nullable=False),
            Column("section", String(100), nullable=True),
            Column("page_start", Integer, nullable=True),
            Column("page_end", Integer, nullable=True),
            Column("chunk_index", Integer, nullable=False, default=0),
            Column("company", String(255), nullable=True),
            Column("fiscal_period", String(20), nullable=True),
            Column("report_type", String(20), nullable=True),
            Column("embedding", Vector(dimension), nullable=False),
        )
        self._metadata = metadata
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            self._metadata.create_all(conn, tables=[self._table])
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS ix_{self._table.name}_embedding_hnsw "
                    f"ON {self._table.name} USING hnsw (embedding vector_cosine_ops)"
                )
            )

    def upsert(self, chunks: Sequence[ChunkRecord]) -> None:
        if not chunks:
            return
        rows: list[dict[str, Any]] = [
            {
                "id": c.id,
                "document_id": c.document_id,
                "user_id": c.user_id,
                "text": c.text,
                "section": c.section,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "chunk_index": c.chunk_index,
                "company": c.company,
                "fiscal_period": c.fiscal_period,
                "report_type": c.report_type,
                "embedding": c.embedding,
            }
            for c in chunks
        ]
        stmt = pg_insert(self._table).values(rows)
        update_cols = {
            col.name: stmt.excluded[col.name] for col in self._table.columns if col.name != "id"
        }
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
        with self._engine.begin() as conn:
            conn.execute(stmt)

    def query(
        self,
        vector: Sequence[float],
        k: int,
        filters: Mapping[str, object],
    ) -> list[ChunkHit]:
        t = self._table
        distance = t.c.embedding.cosine_distance(list(vector))
        stmt = select(t, distance.label("distance")).order_by(distance).limit(k)
        stmt = _apply_filters(stmt, t, filters)
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [
            ChunkHit(
                id=str(row["id"]),
                document_id=str(row["document_id"]),
                text=str(row["text"]),
                score=1.0 - float(row["distance"]),
                section=row["section"],
                page_start=row["page_start"],
                page_end=row["page_end"],
                company=row["company"],
                fiscal_period=row["fiscal_period"],
                report_type=row["report_type"],
            )
            for row in rows
        ]

    def delete_by_document(self, document_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(self._table).where(self._table.c.document_id == document_id))


# Same plural-filter-key -> singular-column mapping as the Chroma adapter (see
# its module for why): `document_ids` is the `VectorStore.query` contract key,
# `document_id` is the column.
_FILTER_TO_COLUMN = {"document_ids": "document_id"}


def _apply_filters(stmt: Select[Any], table: Table, filters: Mapping[str, object]) -> Select[Any]:
    for key, value in filters.items():
        if value is None:
            continue
        col = table.c[_FILTER_TO_COLUMN.get(key, key)]
        if isinstance(value, list | tuple | set):
            stmt = stmt.where(col.in_(list(value)))
        else:
            stmt = stmt.where(col == value)
    return stmt
