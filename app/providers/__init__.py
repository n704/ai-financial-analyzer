"""Provider abstraction: LLM, embeddings, vector-store, market-data, and forecast
protocols + factory.

Protocols live in ``base.py`` (P1.2); the config-driven factory in ``factory.py``
(P1.3) builds concrete adapters from :class:`~app.config.Settings` once at startup.
Only modules under this package (and ``app/infra``, ``app/storage``, ``app/db``)
may import vendor SDKs — everything else depends on the protocols in ``base.py``.
"""

from __future__ import annotations

from app.providers.base import (
    Bar,
    ChunkHit,
    ChunkRecord,
    ContentRef,
    EmbeddingProvider,
    ForecastProvider,
    ForecastResult,
    ForecastUnavailable,
    LLMProvider,
    MarketDataProvider,
    MarketDataUnavailable,
    Message,
    NullUsageSink,
    PriceSeries,
    ProviderError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderRefusal,
    ProviderUnavailable,
    TickerNotFound,
    UsageRecord,
    UsageSink,
    VectorStore,
)
from app.providers.factory import (
    ForecastProviders,
    ProviderBundle,
    build_forecast_providers,
    build_providers,
)

__all__ = [
    "Bar",
    "ChunkHit",
    "ChunkRecord",
    "ContentRef",
    "EmbeddingProvider",
    "ForecastProvider",
    "ForecastProviders",
    "ForecastResult",
    "ForecastUnavailable",
    "LLMProvider",
    "MarketDataProvider",
    "MarketDataUnavailable",
    "Message",
    "NullUsageSink",
    "PriceSeries",
    "ProviderBundle",
    "ProviderError",
    "ProviderInvalidResponse",
    "ProviderRateLimited",
    "ProviderRefusal",
    "ProviderUnavailable",
    "TickerNotFound",
    "UsageRecord",
    "UsageSink",
    "VectorStore",
    "build_forecast_providers",
    "build_providers",
]
