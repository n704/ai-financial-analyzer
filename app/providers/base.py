"""Provider contracts the whole application depends on (P1.2, P6.1).

This module defines the five protocols — :class:`LLMProvider`,
:class:`EmbeddingProvider`, :class:`VectorStore`, and (for F6 forecasting)
:class:`MarketDataProvider` and :class:`ForecastProvider` — plus the value types
that cross the boundary and the small set of typed provider errors. It imports **no vendor
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

import datetime as dt
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
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
# Forecasting value types (F6, P6.1) — arrays and bars only, never prose
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV bar. Market-data adapters normalize vendor rows into this
    shape and are responsible for split/dividend adjustment; ``close`` is the
    adjusted close the forecast pipeline reads."""

    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True, slots=True)
class PriceSeries:
    """A normalized bar series for one ``(ticker, interval)`` from one source,
    stamped with the ``as_of`` date it was fetched for. Public data: cached
    globally, never user-owned (SPEC.md §3.1, §7)."""

    ticker: str
    interval: str
    source: str
    as_of: dt.date
    bars: tuple[Bar, ...]

    def __post_init__(self) -> None:
        if not self.bars:
            raise ValueError(f"PriceSeries for {self.ticker!r} has no bars")
        for previous, current in pairwise(self.bars):
            if current.date <= previous.date:
                raise ValueError(
                    f"PriceSeries bars must be strictly ascending by date; "
                    f"{previous.date} is followed by {current.date}"
                )

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def start(self) -> dt.date:
        return self.bars[0].date

    @property
    def end(self) -> dt.date:
        return self.bars[-1].date

    @property
    def closes(self) -> list[float]:
        return [bar.close for bar in self.bars]

    @property
    def dates(self) -> list[dt.date]:
        return [bar.date for bar in self.bars]


@dataclass(frozen=True, slots=True)
class ForecastResult:
    """What a :class:`ForecastProvider` returns for a batch of contexts: one
    point path per context and, when the provider has a quantile head, one
    path per requested quantile level per context. Carries arrays only — no
    prose — which is why the ``[n]``-citation machinery has no role in F6.

    Shapes: ``point[i][k]`` is series ``i`` at horizon step ``k``;
    ``quantiles[i][j][k]`` is series ``i``, level ``quantile_levels[j]``, step
    ``k``. ``quantiles`` is ``None`` for providers with
    ``supports_quantiles=False`` — the domain layer then derives an empirical
    band from backtest residuals, so a band is never optional downstream.
    """

    point: tuple[tuple[float, ...], ...]
    quantile_levels: tuple[float, ...] = ()
    quantiles: tuple[tuple[tuple[float, ...], ...], ...] | None = None

    def __post_init__(self) -> None:
        if not self.point:
            raise ValueError("ForecastResult.point must contain at least one path")
        horizon = len(self.point[0])
        if any(len(path) != horizon for path in self.point):
            raise ValueError("ForecastResult.point paths must all share one horizon")
        if self.quantiles is None:
            return
        if len(self.quantiles) != len(self.point):
            raise ValueError("ForecastResult.quantiles must have one entry per point path")
        for per_series in self.quantiles:
            if len(per_series) != len(self.quantile_levels):
                raise ValueError("ForecastResult.quantiles must have one path per quantile level")
            if any(len(path) != horizon for path in per_series):
                raise ValueError("ForecastResult quantile paths must match the point horizon")

    @property
    def batch_size(self) -> int:
        return len(self.point)

    @property
    def horizon(self) -> int:
        return len(self.point[0])


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


class TickerNotFound(ProviderError):
    """The market-data source has no series for this symbol — maps to 404 at
    the API edge. Distinct from :class:`MarketDataUnavailable` so a typo'd
    ticker isn't reported as a vendor outage."""

    def __init__(self, ticker: str, *, source: str | None = None) -> None:
        where = f" at {source}" if source else ""
        super().__init__(f"no price series found for ticker {ticker!r}{where}")
        self.ticker = ticker
        self.source = source


class MarketDataUnavailable(ProviderUnavailable):
    """The market-data source is down, rate-limiting, or returned garbage. A
    subclass of :class:`ProviderUnavailable` so it degrades to "forecast
    unavailable" (503), never a 500 (PLAN.md P6.2)."""


class ForecastUnavailable(ProviderUnavailable):
    """The forecasting model could not run (weights missing, device error,
    out-of-range request). Same 503-shaped degradation as above."""


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


@runtime_checkable
class MarketDataProvider(Protocol):
    """End-of-day (or, when ``supports_intraday``, intraday) bar source.

    Adapters own: HTTP + auth, vendor rate limits and backoff, symbol quirks
    (exchange suffixes, share-class separators), split/dividend adjustment,
    and normalizing vendor rows to :class:`PriceSeries`. Core code sends a
    validated ticker symbol and nothing else — never document or user content
    (ARCHITECTURE.md §1, trust boundaries).
    """

    @property
    def provider(self) -> str: ...

    @property
    def supports_intraday(self) -> bool:
        """Whether intervals finer than one day can be requested. Core code
        checks this at startup against ``market_data.interval`` rather than
        discovering it on the first request."""
        ...

    def fetch_series(self, ticker: str, start: dt.date, end: dt.date, interval: str) -> PriceSeries:
        """Bars in ``[start, end]`` for ``ticker``. Raises :class:`TickerNotFound`
        for an unknown symbol and :class:`MarketDataUnavailable` for anything
        the adapter could not turn into bars."""
        ...


@runtime_checkable
class ForecastProvider(Protocol):
    """Zero-shot time-series forecaster over a batch of numeric contexts.

    Adapters own: checkpoint pin + download, model compilation, device and
    dtype, batching/padding, and keeping the model resident. Everything numeric
    around the call — transforms, backtests, bands, skill — is computed in
    ``app/domain/forecast.py`` and is identical for every adapter. The
    capability flags let core code degrade rather than branch on a name:
    no quantile head → empirical bands; no covariate support → univariate
    context only; ``max_context``/``max_horizon`` → the service truncates and
    the factory validates config against them at startup.
    """

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def checkpoint_revision(self) -> str:
        """The pinned weights revision (provenance on every artifact); a
        placeholder such as ``"n/a"`` for models that load no weights."""
        ...

    @property
    def max_context(self) -> int: ...

    @property
    def max_horizon(self) -> int: ...

    @property
    def supports_quantiles(self) -> bool: ...

    @property
    def supports_covariates(self) -> bool: ...

    def forecast(
        self,
        contexts: Sequence[Sequence[float]],
        horizon: int,
        quantiles: Sequence[float],
    ) -> ForecastResult:
        """One point path per context (plus quantile paths when supported).
        Synchronous and CPU-bound by nature — callers run it off the event
        loop via ``TaskQueue`` (ARCHITECTURE.md §2). Raises
        :class:`ForecastUnavailable` when inference cannot run."""
        ...


__all__ = [
    "Bar",
    "ChunkHit",
    "ChunkRecord",
    "ContentRef",
    "EmbeddingProvider",
    "ForecastProvider",
    "ForecastResult",
    "ForecastUnavailable",
    "LLMProvider",
    "MarketDataProvider",
    "MarketDataUnavailable",
    "Message",
    "NullUsageSink",
    "PriceSeries",
    "ProviderError",
    "ProviderInvalidResponse",
    "ProviderRateLimited",
    "ProviderRefusal",
    "ProviderUnavailable",
    "Role",
    "TickerNotFound",
    "UsageRecord",
    "UsageSink",
    "VectorStore",
]
