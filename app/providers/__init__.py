"""Provider abstraction: LLM, embeddings, and vector-store protocols + factory.

Protocols live in ``base.py`` (P1.2); the config-driven factory in ``factory.py``
(P1.3) builds concrete adapters from :class:`~app.config.Settings` once at startup.
Only modules under this package (and ``app/infra``, ``app/storage``, ``app/db``)
may import vendor SDKs — everything else depends on the protocols in ``base.py``.
"""

from __future__ import annotations

from app.providers.base import (
    ChunkHit,
    ChunkRecord,
    ContentRef,
    EmbeddingProvider,
    LLMProvider,
    Message,
    NullUsageSink,
    ProviderError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderRefusal,
    ProviderUnavailable,
    UsageRecord,
    UsageSink,
    VectorStore,
)
from app.providers.factory import ProviderBundle, build_providers

__all__ = [
    "ChunkHit",
    "ChunkRecord",
    "ContentRef",
    "EmbeddingProvider",
    "LLMProvider",
    "Message",
    "NullUsageSink",
    "ProviderBundle",
    "ProviderError",
    "ProviderInvalidResponse",
    "ProviderRateLimited",
    "ProviderRefusal",
    "ProviderUnavailable",
    "UsageRecord",
    "UsageSink",
    "VectorStore",
    "build_providers",
]
