"""Provider contracts the whole application depends on (P1.2).

This module defines the three protocols — :class:`LLMProvider`,
:class:`EmbeddingProvider`, :class:`VectorStore` — plus the value types that cross
the boundary and the small set of typed provider errors. It imports **no vendor
SDK**: everything here is pure typing so ``api``/``services``/``domain`` can depend
on it without pulling Gemini, Redis, or anything else into their import graph.

The rules the rest of the codebase relies on:
- capability is asked, never branched on by name (``supports_pdf_input``);
- structured output returns a validated Pydantic model (the adapter owns the
  provider-specific mechanism + one validation retry);
- provider failures arrive as one of the typed errors below, never as a raw SDK
  exception.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

Role = Literal["user", "assistant"]
TModel = TypeVar("TModel", bound=BaseModel)


# --------------------------------------------------------------------------- #
# Value types crossing the provider boundary
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ContentRef:
    """A handle to a document already uploaded to a provider's file store.

    Cached on ``documents.provider_file_ref`` so a PDF is uploaded once and reused
    across analysis calls. ``provider`` records which adapter minted it, so a stale
    ref from a different provider is never replayed.
    """

    provider: str
    ref: str
    mime_type: str = "application/pdf"


@dataclass(slots=True)
class Message:
    """One chat turn. ``attachments`` carries provider file refs (native-PDF path);
    text-only providers ignore them and read the parsed-text path instead."""

    role: Role
    content: str
    attachments: tuple[ContentRef, ...] = ()


@dataclass(slots=True)
class ChunkRecord:
    """A chunk to index: the embedding plus the metadata used for filtered
    retrieval. ``user_id`` is carried so every vector is scoped to its owner."""

    id: str
    document_id: str
    user_id: str
    text: str
    embedding: list[float]
    section: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    chunk_index: int = 0
    company: str | None = None
    fiscal_period: str | None = None
    report_type: str | None = None


@dataclass(slots=True)
class ChunkHit:
    """A retrieval result: the chunk text, its similarity score, and page metadata
    for citation rendering."""

    id: str
    document_id: str
    text: str
    score: float
    section: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    company: str | None = None
    fiscal_period: str | None = None
    report_type: str | None = None


@dataclass(slots=True)
class UsageRecord:
    """Token accounting for a single provider call. The adapter reports it; the
    caller attributes it to a user and persists it to the ``usage`` table."""

    kind: Literal["llm", "embedding"]
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


class UsageSink(Protocol):
    """Where adapters report token usage. A DB-backed sink lands with the ``usage``
    table; until then adapters are constructed with :class:`NullUsageSink`."""

    def record(self, usage: UsageRecord) -> None: ...


class NullUsageSink:
    """Drops usage on the floor. Default until the ``usage`` table is wired."""

    def record(self, usage: UsageRecord) -> None:
        return None


# --------------------------------------------------------------------------- #
# Typed provider errors — adapters normalize every SDK failure into one of these
# --------------------------------------------------------------------------- #
class ProviderError(Exception):
    """Base for all normalized provider failures."""


class ProviderRateLimited(ProviderError):
    """Provider returned a rate-limit / quota signal (HTTP 429). Carries an optional
    ``retry_after`` (seconds) the API can surface as a retry hint."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """Provider is down / unreachable / 5xx — maps to a 503 at the API edge."""


class ProviderRefusal(ProviderError):
    """Provider refused to answer (safety block / content policy) — maps to 422."""


class ProviderInvalidResponse(ProviderError):
    """Structured output failed schema validation even after the adapter's retry."""


# --------------------------------------------------------------------------- #
# Protocols
# --------------------------------------------------------------------------- #
@runtime_checkable
class LLMProvider(Protocol):
    """Text generation + structured extraction, streaming-first.

    Adapters own: SDK calls, auth, streaming mechanics, schema→provider mapping
    with one validation retry, 429-aware backoff, error normalization, and any
    provider-specific optimization (prompt caching, thinking budgets). Core code
    sees only this interface and the typed errors above.
    """

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def supports_pdf_input(self) -> bool:
        """Whether the model reads attached PDFs visually. When False, callers use
        the parsed-text path instead of attaching a :class:`ContentRef`."""
        ...

    def generate(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """Stream the model's text response as chunks."""
        ...

    def generate_structured(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        schema: type[TModel],
        max_tokens: int | None = None,
    ) -> TModel:
        """Return a validated instance of ``schema`` (adapter maps + retries once)."""
        ...

    def attach_pdf(self, *, data: bytes, display_name: str) -> ContentRef:
        """Upload a PDF to the provider's file store and return a reusable handle.
        Providers with ``supports_pdf_input=False`` raise ``NotImplementedError``."""
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Batch + single-text embedding. ``dimension`` feeds the ``index_meta`` guard
    so a config change that alters vector size is caught before it corrupts an
    index."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class VectorStore(Protocol):
    """Vector upsert / filtered query / per-document delete. Filters always include
    ``user_id`` (multi-user isolation) and optionally ``document_ids``."""

    def upsert(self, chunks: Sequence[ChunkRecord]) -> None: ...

    def query(
        self,
        vector: Sequence[float],
        k: int,
        filters: Mapping[str, object],
    ) -> list[ChunkHit]: ...

    def delete_by_document(self, document_id: str) -> None: ...


__all__ = [
    "ChunkHit",
    "ChunkRecord",
    "ContentRef",
    "EmbeddingProvider",
    "LLMProvider",
    "Message",
    "NullUsageSink",
    "ProviderError",
    "ProviderInvalidResponse",
    "ProviderRateLimited",
    "ProviderRefusal",
    "ProviderUnavailable",
    "Role",
    "UsageRecord",
    "UsageSink",
    "VectorStore",
]
