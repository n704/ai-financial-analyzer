"""Configuration loading, profiles, and validation (P1.1).

Public surface: the typed :class:`Settings` tree, the :func:`load_settings`
loader, and :class:`ConfigError`. Everything downstream depends on ``Settings``,
never on YAML or ``os.environ`` directly.
"""

from __future__ import annotations

from app.config.errors import ConfigError
from app.config.loader import DEFAULT_CONFIG_PATH, load_settings
from app.config.models import (
    AuthConfig,
    CacheConfig,
    ChunkingConfig,
    DatabaseConfig,
    EmbeddingConfig,
    EventsConfig,
    LimitsConfig,
    LLMConfig,
    ObjectStorageConfig,
    QueueConfig,
    QuotasConfig,
    RateLimitConfig,
    Settings,
    VectorStoreConfig,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "AuthConfig",
    "CacheConfig",
    "ChunkingConfig",
    "ConfigError",
    "DatabaseConfig",
    "EmbeddingConfig",
    "EventsConfig",
    "LLMConfig",
    "LimitsConfig",
    "ObjectStorageConfig",
    "QueueConfig",
    "QuotasConfig",
    "RateLimitConfig",
    "Settings",
    "VectorStoreConfig",
    "load_settings",
]
