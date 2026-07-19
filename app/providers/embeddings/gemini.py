"""Gemini embedding adapter (P1.6) — default embedding provider.

Wraps ``google-genai``'s ``embed_content`` behind
:class:`~app.providers.base.EmbeddingProvider`. Documents and queries use
different Gemini task types (``RETRIEVAL_DOCUMENT`` vs ``RETRIEVAL_QUERY``) —
asymmetric embeddings retrieve noticeably better than treating both the same way.
Batches documents in one call; retries 429s/5xxs with the shared backoff helper.
"""

from __future__ import annotations

from collections.abc import Sequence

from google.genai import Client, types

from app.providers._gemini_errors import gemini_retry_hint, to_provider_error
from app.providers.base import NullUsageSink, ProviderUnavailable, UsageRecord, UsageSink
from app.providers.retry import with_backoff


class GeminiEmbeddingProvider:
    """Gemini implementation of :class:`~app.providers.base.EmbeddingProvider`."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimension: int = 3072,  # gemini-embedding-001 native size
        usage_sink: UsageSink | None = None,
        max_retries: int = 5,
    ) -> None:
        self._model = model
        self._dimension = dimension
        self._usage: UsageSink = usage_sink or NullUsageSink()
        self._max_retries = max_retries
        self._client = Client(api_key=api_key)

    @property
    def provider(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed(self, texts: Sequence[str], *, task_type: str) -> list[list[float]]:
        if not texts:
            return []

        config = types.EmbedContentConfig(
            task_type=task_type, output_dimensionality=self._dimension
        )

        def call() -> types.EmbedContentResponse:
            return self._client.models.embed_content(
                model=self._model,
                contents=list(texts),  # type: ignore[arg-type]  # SDK union is list-invariant
                config=config,
            )

        try:
            response = with_backoff(
                call, is_retryable=gemini_retry_hint, max_retries=self._max_retries
            )
        except Exception as exc:
            raise to_provider_error(exc) from exc

        embeddings = response.embeddings
        if embeddings is None or len(embeddings) != len(texts):
            raise ProviderUnavailable(
                f"gemini returned {0 if embeddings is None else len(embeddings)} "
                f"embeddings for {len(texts)} inputs"
            )

        self._usage.record(
            UsageRecord(
                kind="embedding",
                provider="gemini",
                model=self._model,
                tokens_in=sum(len(t.split()) for t in texts),
            )
        )

        return [list(e.values or []) for e in embeddings]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], task_type="RETRIEVAL_QUERY")[0]
