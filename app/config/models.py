"""Typed configuration schema (SPEC.md §4).

Every swappable component — LLM, embeddings, vector store, database, cache, queue,
event bus, object storage — is a field here. Application code reads these typed
models; it never re-parses YAML or inspects env vars directly. Secrets are *named*
here (``api_key_env``), never *stored* here: the resolver reads the env var on
demand so a Settings object can be safely held in memory without holding secrets.
"""

from __future__ import annotations

import os
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


class QuotasConfig(_Base):
    documents: int = 100
    uploads_per_day: int = 20
    questions_per_day: int = 200


class LimitsConfig(_Base):
    max_upload_mb: int = 30
    max_pages: int = 600
    max_compare_docs: int = 5
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
        return self

    @property
    def is_multiprocess(self) -> bool:
        """True when the config describes an API + separate-worker topology."""
        return self.queue.backend == "arq"
