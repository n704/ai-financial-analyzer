"""P1.9: Chroma vector store — upsert/query/delete round-trip + multi-user
isolation. This module imports the adapter directly (not through the
provider factory) so it has no dependency on the rest of P1 wiring."""

from __future__ import annotations

from pathlib import Path

from app.providers.base import ChunkRecord
from app.providers.vectorstores.chroma import ChromaVectorStore


def _record(
    id_: str, *, user_id: str = "u1", document_id: str = "d1", embedding: list[float]
) -> ChunkRecord:
    return ChunkRecord(
        id=id_,
        document_id=document_id,
        user_id=user_id,
        text=f"text for {id_}",
        embedding=embedding,
        section="MD&A",
        page_start=1,
        page_end=2,
        chunk_index=0,
        company="Acme",
        fiscal_period="FY2025",
        report_type="10-K",
    )


def test_upsert_and_query_round_trip(tmp_path: Path) -> None:
    store = ChromaVectorStore(path=str(tmp_path / "chroma"))
    store.upsert(
        [
            _record("a", embedding=[1.0, 0.0]),
            _record("b", embedding=[0.0, 1.0]),
        ]
    )

    hits = store.query([1.0, 0.0], k=2, filters={"user_id": "u1"})
    assert next(h.id for h in hits) == "a"
    assert hits[0].section == "MD&A"
    assert hits[0].page_start == 1
    assert hits[0].company == "Acme"
    assert hits[0].score > hits[1].score


def test_query_scopes_by_user_id(tmp_path: Path) -> None:
    store = ChromaVectorStore(path=str(tmp_path / "chroma"))
    store.upsert(
        [
            _record("a", user_id="alice", embedding=[1.0, 0.0]),
            _record("b", user_id="bob", embedding=[1.0, 0.0]),
        ]
    )

    hits = store.query([1.0, 0.0], k=10, filters={"user_id": "alice"})
    assert {h.id for h in hits} == {"a"}


def test_query_filters_by_document_ids(tmp_path: Path) -> None:
    store = ChromaVectorStore(path=str(tmp_path / "chroma"))
    store.upsert(
        [
            _record("a", document_id="doc1", embedding=[1.0, 0.0]),
            _record("b", document_id="doc2", embedding=[1.0, 0.0]),
        ]
    )

    hits = store.query([1.0, 0.0], k=10, filters={"user_id": "u1", "document_ids": ["doc1"]})
    assert {h.id for h in hits} == {"a"}


def test_query_empty_document_ids_matches_nothing(tmp_path: Path) -> None:
    """An empty document scope must never silently fall back to "everything"
    — that would leak other documents into a supposedly-scoped query."""
    store = ChromaVectorStore(path=str(tmp_path / "chroma"))
    store.upsert([_record("a", embedding=[1.0, 0.0])])

    hits = store.query([1.0, 0.0], k=10, filters={"user_id": "u1", "document_ids": []})
    assert hits == []


def test_delete_by_document(tmp_path: Path) -> None:
    store = ChromaVectorStore(path=str(tmp_path / "chroma"))
    store.upsert(
        [
            _record("a", document_id="doc1", embedding=[1.0, 0.0]),
            _record("b", document_id="doc2", embedding=[0.0, 1.0]),
        ]
    )

    store.delete_by_document("doc1")

    hits = store.query([1.0, 0.0], k=10, filters={"user_id": "u1"})
    assert {h.id for h in hits} == {"b"}


def test_upsert_overwrites_existing_id(tmp_path: Path) -> None:
    store = ChromaVectorStore(path=str(tmp_path / "chroma"))
    store.upsert([_record("a", embedding=[1.0, 0.0])])
    store.upsert([_record("a", embedding=[0.0, 1.0])])

    hits = store.query([0.0, 1.0], k=10, filters={"user_id": "u1"})
    assert len(hits) == 1
    assert hits[0].id == "a"
