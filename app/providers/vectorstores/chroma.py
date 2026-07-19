"""Chroma vector store adapter (P1.9) — default, local, no server required.

Wraps ``chromadb.PersistentClient`` behind :class:`~app.providers.base.VectorStore`.
Filters always scope by ``user_id`` (multi-user isolation); ``document_ids``
narrows further when a query is scoped to specific reports. The collection is
configured for cosine distance so scores are comparable across embedding models
of different magnitudes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import chromadb

from app.providers.base import ChunkHit, ChunkRecord

# The generic retrieval filter is plural (`document_ids: [...]`, matching the
# `VectorStore.query` contract used by every backend), but the metadata field
# stored per-chunk is singular (`document_id`) — one chunk belongs to one
# document. This maps the former to an `$in` over the latter.
_FILTER_TO_METADATA_KEY = {"document_ids": "document_id"}


def _build_where(filters: Mapping[str, object]) -> dict[str, Any] | None:
    """Translate the generic filter mapping into Chroma's ``where`` shape.

    Chroma requires an explicit ``$and`` once more than one condition is
    present — a bare multi-key dict is not implicitly ANDed.
    """
    clauses: list[dict[str, Any]] = []
    for key, value in filters.items():
        if value is None:
            continue
        metadata_key = _FILTER_TO_METADATA_KEY.get(key, key)
        if isinstance(value, list | tuple | set):
            values = list(value)
            if not values:
                # An empty "must be one of these" can never match anything;
                # short-circuit to an always-false clause rather than silently
                # dropping the filter (which would return other users' data).
                clauses.append({metadata_key: {"$in": ["__never_matches__"]}})
            else:
                clauses.append({metadata_key: {"$in": values}})
        else:
            clauses.append({metadata_key: value})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


class ChromaVectorStore:
    """Chroma implementation of :class:`~app.providers.base.VectorStore`."""

    def __init__(self, *, path: str, collection: str = "chunks") -> None:
        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            collection, metadata={"hnsw:space": "cosine"}
        )

    def upsert(self, chunks: Sequence[ChunkRecord]) -> None:
        if not chunks:
            return
        self._collection.upsert(
            ids=[c.id for c in chunks],
            # chromadb's stub union is invariant over the inner list element type,
            # so a plain `list[list[float]]` never structurally matches it.
            embeddings=[c.embedding for c in chunks],  # type: ignore[arg-type]
            documents=[c.text for c in chunks],
            metadatas=[
                {
                    "document_id": c.document_id,
                    "user_id": c.user_id,
                    "section": c.section or "",
                    "page_start": c.page_start if c.page_start is not None else -1,
                    "page_end": c.page_end if c.page_end is not None else -1,
                    "chunk_index": c.chunk_index,
                    "company": c.company or "",
                    "fiscal_period": c.fiscal_period or "",
                    "report_type": c.report_type or "",
                }
                for c in chunks
            ],
        )

    def query(
        self,
        vector: Sequence[float],
        k: int,
        filters: Mapping[str, object],
    ) -> list[ChunkHit]:
        where = _build_where(filters)
        result = self._collection.query(
            query_embeddings=[list(vector)],  # type: ignore[arg-type]  # see upsert() above
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        ids = result["ids"][0] if result["ids"] else []
        if not ids:
            return []
        documents = result["documents"][0] if result["documents"] else [None] * len(ids)
        metadatas = result["metadatas"][0] if result["metadatas"] else [{}] * len(ids)
        distances = result["distances"][0] if result["distances"] else [None] * len(ids)

        hits: list[ChunkHit] = []
        for chunk_id, doc_text, meta, distance in zip(
            ids, documents, metadatas, distances, strict=True
        ):
            meta = meta or {}
            # Cosine distance -> cosine similarity.
            score = 1.0 - distance if distance is not None else 0.0
            hits.append(
                ChunkHit(
                    id=chunk_id,
                    document_id=str(meta.get("document_id", "")),
                    text=doc_text or "",
                    score=score,
                    section=_none_if_blank(meta.get("section")),
                    page_start=_none_if_sentinel(meta.get("page_start")),
                    page_end=_none_if_sentinel(meta.get("page_end")),
                    company=_none_if_blank(meta.get("company")),
                    fiscal_period=_none_if_blank(meta.get("fiscal_period")),
                    report_type=_none_if_blank(meta.get("report_type")),
                )
            )
        return hits

    def delete_by_document(self, document_id: str) -> None:
        self._collection.delete(where={"document_id": document_id})


def _none_if_blank(value: object) -> str | None:
    return None if value in (None, "") else str(value)


def _none_if_sentinel(value: object) -> int | None:
    if value is None or value == -1:
        return None
    assert isinstance(value, int | float)
    return int(value)
