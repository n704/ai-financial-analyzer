"""Typed configuration schema (SPEC.md §4).

Every swappable component — LLM, embeddings, vector store, database, cache, queue,
event bus, object storage, market-data source, forecasting model — is a field
here. Application code reads these typed models; it never re-parses YAML or
inspects env vars directly. Secrets are *named* here (``api_key_env``), never
*stored* here: the resolver reads the env var on demand so a Settings object can
be safely held in memory without holding secrets.
"""

from __future__ import annotations

import os
import re
from itertools import pairwise
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.config.errors import ConfigError


class _Base(BaseModel):
    """Forbid unknown keys so a typo in a profile fails fast instead of silently."""

    model_config = ConfigDict(extra="forbid")


class _KeyedProvider(_Base):
    """Shared shape for provider blocks that authenticate via a named env var."""

    provider: str
    model: str
    api_key_env: str | None = None
    base_url: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)

    def resolve_api_key(self) -> SecretStr | None:
        """Read the secret from its env var on demand. ``None`` when unauthenticated
        (fake provider, local Ollama). Missing-but-required → fail fast."""
        if self.api_key_env is None:
            return None
        value = os.environ.get(self.api_key_env)
        if not value:
            raise ConfigError(
                f"provider '{self.provider}' names api_key_env='{self.api_key_env}', "
                f"but that environment variable is unset or empty"
            )
        return SecretStr(value)


class LLMConfig(_KeyedProvider):
    """LLM provider selection. ``options`` carries provider-tuning (e.g.
    ``max_output_tokens``) that adapters interpret; core code never reads it."""


class EmbeddingConfig(_KeyedProvider):
    """Embedding provider selection."""


class VectorStoreConfig(_Base):
    provider: str
    path: str | None = None  # chroma/faiss local path; pgvector reuses database.url
    collection: str = "chunks"


class DatabaseConfig(_Base):
    url: str


class CacheConfig(_Base):
    backend: Literal["memory", "redis"] = "memory"
    url: str | None = None


class QueueConfig(_Base):
    backend: Literal["inprocess", "arq"] = "inprocess"
    url: str | None = None


class EventsConfig(_Base):
    backend: Literal["inprocess", "redis"] = "inprocess"
    url: str | None = None


class ObjectStorageConfig(_Base):
    provider: Literal["local", "s3"] = "local"
    path: str | None = None  # local root
    bucket: str | None = None  # s3
    endpoint_env: str | None = None  # s3 endpoint (env-var name)
    region: str | None = None
    access_key_env: str = "S3_ACCESS_KEY"
    secret_key_env: str = "S3_SECRET_KEY"
    signed_url_ttl_s: int = 300
    # Local-storage signed URLs are self-issued (no external service to sign
    # them), so they need their own HMAC secret — deliberately separate from
    # `auth.secret_env` (JWT signing): different blast radius, different
    # rotation schedule.
    signing_secret_env: str = "OBJECT_STORAGE_SIGNING_SECRET"

    def resolve_signing_secret(self) -> SecretStr:
        value = os.environ.get(self.signing_secret_env)
        if not value:
            raise ConfigError(
                f"object_storage.signing_secret_env='{self.signing_secret_env}' "
                f"is unset or empty; set a strong secret for signing local file URLs"
            )
        return SecretStr(value)


class ChunkingConfig(_Base):
    target_tokens: int = 800
    overlap_tokens: int = 100


# Bar intervals: a count plus a unit. Sub-daily units need a market-data source
# with `supports_intraday=True` (checked by the factory at startup, never on the
# first request); the default `1d` is what every source, incl. `fixture`, serves.
_INTERVAL = re.compile(r"^(\d+)(m|h|d|wk|mo)$")
_INTRADAY_UNITS = frozenset({"m", "h"})

ForecastTransform = Literal["level", "log", "log_return"]
ForecastDevice = Literal["cpu", "cuda", "mps"]


def is_bar_interval(value: str) -> bool:
    """Whether ``value`` is a well-formed bar interval (``1d``, ``1wk``, ``5m``...).
    Shared by the config check and the forecast API's per-request validation."""
    return _INTERVAL.fullmatch(value) is not None


class MarketDataConfig(_Base):
    """Market-data source selection (F6). ``fixture`` is hermetic (deterministic
    synthetic bars — CI and the offline profile); ``stooq`` is the keyless live
    EOD source; keyed vendors name their key via ``api_key_env``."""

    provider: str = "fixture"
    api_key_env: str | None = None
    interval: str = "1d"
    max_history_days: int = Field(default=3650, ge=30)
    cache_ttl_s: int = Field(default=900, ge=0)
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_interval(self) -> MarketDataConfig:
        if not _INTERVAL.fullmatch(self.interval):
            raise ConfigError(
                f"market_data.interval={self.interval!r} is not a bar interval "
                f"(expected <count><unit>, unit in m|h|d|wk|mo, e.g. '1d')"
            )
        return self

    @property
    def is_intraday(self) -> bool:
        match = _INTERVAL.fullmatch(self.interval)
        return match is not None and match.group(2) in _INTRADAY_UNITS

    def resolve_api_key(self) -> SecretStr | None:
        if self.api_key_env is None:
            return None
        value = os.environ.get(self.api_key_env)
        if not value:
            raise ConfigError(
                f"market_data.provider '{self.provider}' names "
                f"api_key_env='{self.api_key_env}', but that environment variable "
                f"is unset or empty"
            )
        return SecretStr(value)


class ForecastConfig(_Base):
    """Forecasting model selection (F6, SPEC.md §3.6/§4).

    ``enabled`` defaults to ``False``: torch plus a 200M-parameter checkpoint are
    not "zero external services", so F6 is a deliberate opt-in
    (``uv sync --extra forecast``). ``provider: naive`` is a fully working,
    dependency-free configuration — the baselines exposed as a provider — so the
    whole flow runs and is testable with torch absent (PLAN.md P6.4).

    ``model``/``revision`` pin the checkpoint (provenance on every artifact);
    ``weights_license_ack`` is the license gate — non-commercially-licensed
    weights (TimesFM 3.0) refuse to load without it, and unknown checkpoints are
    treated as restricted (ARCHITECTURE.md §3, "Forecast weights & the license
    guard"). ``options`` carries adapter tuning (``naive``: ``method``;
    ``timesfm``: ``torch_compile``, ``normalize_inputs``) that core code never
    reads.
    """

    enabled: bool = False
    provider: str = "naive"
    model: str = "google/timesfm-2.5-200m-pytorch"
    revision: str = "main"
    weights_license_ack: bool = False
    device: ForecastDevice = "cpu"
    max_context: int = Field(default=1024, ge=16)
    max_horizon: int = Field(default=256, ge=1)
    transform: ForecastTransform = "log"
    quantiles: list[float] = Field(
        default_factory=lambda: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    )
    backtest_windows: int = Field(default=8, ge=1)
    cache_ttl_s: int = Field(default=3600, ge=0)
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_quantiles(self) -> ForecastConfig:
        """The band is not optional (SPEC.md §3.6): every forecast ships its
        median and its 10-90% interval, so those three levels are mandatory,
        and the list must be a strictly increasing set of probabilities."""
        levels = self.quantiles
        if any(not 0.0 < q < 1.0 for q in levels):
            raise ConfigError("forecast.quantiles must all lie strictly between 0 and 1")
        if any(b <= a for a, b in pairwise(levels)):
            raise ConfigError("forecast.quantiles must be strictly increasing")
        for required in (0.1, 0.5, 0.9):
            if not any(abs(q - required) < 1e-9 for q in levels):
                raise ConfigError(
                    f"forecast.quantiles must include {required} — the median path "
                    f"and the 10-90% band are mandatory on every forecast"
                )
        return self


class QuotasConfig(_Base):
    documents: int = 100
    uploads_per_day: int = 20
    questions_per_day: int = 200
    forecasts_per_day: int = 50


class LimitsConfig(_Base):
    max_upload_mb: int = 30
    max_pages: int = 600
    max_compare_docs: int = 5
    # Trading days. Beyond this the rolling-origin backtest can't support the
    # claim (SPEC.md §4; open question #10 keeps the exact cap adjustable).
    max_forecast_horizon: int = Field(default=120, ge=1)
    quotas: QuotasConfig = Field(default_factory=QuotasConfig)


class AuthConfig(_Base):
    """JWT + refresh-token policy. The signing secret is named, not stored."""

    secret_env: str = "JWT_SECRET"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    jwt_algorithm: str = "HS256"

    def resolve_secret(self) -> SecretStr:
        value = os.environ.get(self.secret_env)
        if not value:
            raise ConfigError(
                f"auth.secret_env='{self.secret_env}' is unset or empty; "
                f"set a strong signing secret for JWTs"
            )
        return SecretStr(value)


class RateLimitConfig(_Base):
    """Per-IP and per-user request budgets enforced at the API edge via ``Cache``."""

    per_ip_per_minute: int = 120
    per_user_per_minute: int = 300
    auth_per_ip_per_minute: int = 20  # stricter on register/login


class Settings(_Base):
    """The fully-resolved, typed application configuration."""

    llm: LLMConfig
    embeddings: EmbeddingConfig
    vector_store: VectorStoreConfig
    database: DatabaseConfig
    cache: CacheConfig = Field(default_factory=CacheConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    object_storage: ObjectStorageConfig = Field(default_factory=ObjectStorageConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    forecast: ForecastConfig = Field(default_factory=ForecastConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)

    @model_validator(mode="after")
    def _check_backend_coherence(self) -> Settings:
        """Reject infra combinations that cannot work as configured.

        Two classes of error, both caught at load rather than at first use:
        - a Redis-backed backend without a URL, and
        - in-memory backends paired with a multi-process queue (their state lives
          in one process, so a separate arq worker could never see it).
        """
        if self.cache.backend == "redis" and not self.cache.url:
            raise ConfigError("cache.backend='redis' requires cache.url")
        if self.queue.backend == "arq" and not self.queue.url:
            raise ConfigError("queue.backend='arq' requires queue.url")
        if self.events.backend == "redis" and not self.events.url:
            raise ConfigError("events.backend='redis' requires events.url")

        if self.queue.backend == "arq":
            # arq means a separate worker process; per-process in-memory state can't
            # be shared with it. Force the coherent multi-process backends.
            if self.cache.backend != "redis":
                raise ConfigError(
                    "queue.backend='arq' runs a separate worker, so cache.backend "
                    "must be 'redis' (in-memory cache is per-process)"
                )
            if self.events.backend != "redis":
                raise ConfigError(
                    "queue.backend='arq' runs a separate worker, so events.backend "
                    "must be 'redis' (in-memory event bus is per-process)"
                )

        if self.vector_store.provider == "pgvector" and not self.database.url.startswith(
            ("postgresql", "postgres")
        ):
            raise ConfigError("vector_store.provider='pgvector' requires a PostgreSQL database.url")

        # The API validates a requested horizon against limits.max_forecast_horizon
        # before queueing; if that could exceed what the model is compiled for,
        # the job would fail after the 202. Catch it at load instead.
        if self.forecast.enabled and self.limits.max_forecast_horizon > self.forecast.max_horizon:
            raise ConfigError(
                f"limits.max_forecast_horizon={self.limits.max_forecast_horizon} exceeds "
                f"forecast.max_horizon={self.forecast.max_horizon}; the API would accept "
                f"horizons the forecasting model is not compiled to serve"
            )
        return self

    @property
    def is_multiprocess(self) -> bool:
        """True when the config describes an API + separate-worker topology."""
        return self.queue.backend == "arq"
