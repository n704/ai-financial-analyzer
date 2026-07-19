"""P1.11: object-storage factory — config selects local vs. S3 with no code
change, and fails fast on missing required fields/secrets."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import ConfigError, Settings
from app.storage.factory import build_object_storage
from app.storage.local import LocalObjectStorage


def _settings(**object_storage: object) -> Settings:
    return Settings.model_validate(
        {
            "llm": {"provider": "fake", "model": "fake"},
            "embeddings": {"provider": "fake", "model": "fake"},
            "vector_store": {"provider": "chroma", "path": "./data/chroma"},
            "database": {"url": "sqlite:///:memory:"},
            "object_storage": object_storage,
        }
    )


def test_build_local_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBJECT_STORAGE_SIGNING_SECRET", "test-secret")
    settings = _settings(provider="local", path=str(tmp_path))
    storage = build_object_storage(settings)
    assert isinstance(storage, LocalObjectStorage)


def test_local_storage_without_signing_secret_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OBJECT_STORAGE_SIGNING_SECRET", raising=False)
    settings = _settings(provider="local", path=str(tmp_path))
    with pytest.raises(ConfigError, match="signing_secret_env"):
        build_object_storage(settings)


def test_s3_without_bucket_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBJECT_STORAGE_SIGNING_SECRET", "test-secret")
    settings = _settings(provider="s3")
    with pytest.raises(ConfigError, match="bucket"):
        build_object_storage(settings)


def test_unknown_provider_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBJECT_STORAGE_SIGNING_SECRET", "test-secret")
    settings = _settings(provider="local", path=str(tmp_path))
    settings = settings.model_copy(
        update={"object_storage": settings.object_storage.model_copy(update={"provider": "gcs"})}
    )
    with pytest.raises(ConfigError, match=r"object_storage\.provider"):
        build_object_storage(settings)
