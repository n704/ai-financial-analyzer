"""P1.1 config loader: valid profiles load; invalid config fails fast and clearly."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.config import ConfigError, Settings, load_settings


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "cfg.yaml"
    path.write_text(textwrap.dedent(body))
    return path


def test_dev_profile_loads() -> None:
    settings = load_settings("config/dev.yaml")
    assert settings.llm.provider == "gemini"
    assert settings.llm.model == "gemini-2.5-flash"
    assert settings.database.url.startswith("sqlite")
    assert settings.cache.backend == "memory"
    assert settings.queue.backend == "inprocess"
    assert settings.is_multiprocess is False
    assert settings.limits.quotas.documents == 100


def test_offline_profile_loads() -> None:
    settings = load_settings("config/offline.yaml")
    assert settings.llm.provider == "ollama"
    assert settings.embeddings.provider == "local"
    assert settings.vector_store.collection == "chunks_offline"


def test_scaled_profile_interpolates_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/app")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    settings = load_settings("config/scaled.yaml")
    assert settings.database.url == "postgresql+psycopg://u:p@db:5432/app"
    assert settings.cache.url == "redis://redis:6379/0"
    assert settings.queue.backend == "arq"
    assert settings.is_multiprocess is True


def test_missing_env_ref_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_settings("config/scaled.yaml")


def test_unknown_key_rejected(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path,
        """
        llm: {provider: fake, model: fake}
        embeddings: {provider: fake, model: fake}
        vector_store: {provider: chroma, path: ./data/chroma}
        database: {url: "sqlite:///./x.db"}
        typo_key: 1
        """,
    )
    with pytest.raises(ConfigError):
        load_settings(cfg)


def test_redis_cache_without_url_rejected(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path,
        """
        llm: {provider: fake, model: fake}
        embeddings: {provider: fake, model: fake}
        vector_store: {provider: chroma, path: ./data/chroma}
        database: {url: "sqlite:///./x.db"}
        cache: {backend: redis}
        """,
    )
    with pytest.raises(ConfigError, match=r"cache\.url"):
        load_settings(cfg)


def test_arq_requires_redis_cache_and_events(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path,
        """
        llm: {provider: fake, model: fake}
        embeddings: {provider: fake, model: fake}
        vector_store: {provider: chroma, path: ./data/chroma}
        database: {url: "sqlite:///./x.db"}
        queue: {backend: arq, url: "redis://x"}
        cache: {backend: memory}
        """,
    )
    with pytest.raises(ConfigError, match=r"cache\.backend"):
        load_settings(cfg)


def test_pgvector_requires_postgres(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path,
        """
        llm: {provider: fake, model: fake}
        embeddings: {provider: fake, model: fake}
        vector_store: {provider: pgvector}
        database: {url: "sqlite:///./x.db"}
        """,
    )
    with pytest.raises(ConfigError, match="pgvector"):
        load_settings(cfg)


def test_missing_file_fails_fast() -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings("config/does-not-exist.yaml")


def test_api_key_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings.model_validate(
        {
            "llm": {"provider": "gemini", "model": "m", "api_key_env": "SOME_KEY"},
            "embeddings": {"provider": "fake", "model": "fake"},
            "vector_store": {"provider": "chroma", "path": "./data/chroma"},
            "database": {"url": "sqlite:///./x.db"},
        }
    )
    monkeypatch.delenv("SOME_KEY", raising=False)
    with pytest.raises(ConfigError, match="SOME_KEY"):
        settings.llm.resolve_api_key()

    monkeypatch.setenv("SOME_KEY", "secret-value")
    resolved = settings.llm.resolve_api_key()
    assert resolved is not None
    assert resolved.get_secret_value() == "secret-value"
    # Secret must not leak through the default repr.
    assert "secret-value" not in repr(resolved)

    # Fake provider carries no key.
    assert settings.embeddings.resolve_api_key() is None
