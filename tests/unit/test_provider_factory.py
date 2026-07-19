"""P1.3: the provider factory builds adapters from config with no code change,
and P1.9's embedding-space guard runs as part of that build.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.config import ConfigError, Settings
from app.db.base import Base, build_engine, build_session_factory
from app.providers.embeddings.fake import FakeEmbeddingProvider
from app.providers.factory import build_providers, check_embedding_space
from app.providers.llm.fake import FakeLLMProvider
from app.providers.vectorstores.chroma import ChromaVectorStore


@pytest.fixture
def session() -> Iterator[Session]:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def _fake_settings(tmp_path_str: str) -> Settings:
    return Settings.model_validate(
        {
            "llm": {"provider": "fake", "model": "fake-llm"},
            "embeddings": {"provider": "fake", "model": "fake-embedding"},
            "vector_store": {"provider": "chroma", "path": tmp_path_str},
            "database": {"url": "sqlite:///:memory:"},
        }
    )


def test_build_providers_returns_matching_adapters(tmp_path: object, session: Session) -> None:
    settings = _fake_settings(str(tmp_path))
    bundle = build_providers(settings, session=session)

    assert isinstance(bundle.llm, FakeLLMProvider)
    assert isinstance(bundle.embeddings, FakeEmbeddingProvider)
    assert isinstance(bundle.vector_store, ChromaVectorStore)


def test_unknown_llm_provider_raises_config_error(session: Session, tmp_path: object) -> None:
    settings = _fake_settings(str(tmp_path))
    settings = settings.model_copy(
        update={"llm": settings.llm.model_copy(update={"provider": "nope"})}
    )
    with pytest.raises(ConfigError, match=r"llm\.provider"):
        build_providers(settings, session=session)


def test_gemini_llm_without_api_key_env_raises(session: Session, tmp_path: object) -> None:
    settings = _fake_settings(str(tmp_path))
    settings = settings.model_copy(
        update={
            "llm": settings.llm.model_copy(
                update={"provider": "gemini", "model": "gemini-2.5-flash"}
            )
        }
    )
    with pytest.raises(ConfigError, match="gemini"):
        build_providers(settings, session=session)


def test_embedding_guard_records_on_first_run(tmp_path: object, session: Session) -> None:
    check_embedding_space(_fake_settings(str(tmp_path)), dimension=16, session=session)

    from app.db.repositories import IndexMetaRepository

    row = IndexMetaRepository(session).get()
    assert row is not None
    assert row.embedding_provider == "fake"
    assert row.dimension == 16


def test_embedding_guard_hard_errors_on_mismatch(tmp_path: object, session: Session) -> None:
    settings = _fake_settings(str(tmp_path))
    check_embedding_space(settings, dimension=16, session=session)

    with pytest.raises(ConfigError, match="embedding configuration changed"):
        check_embedding_space(settings, dimension=32, session=session)


def test_embedding_guard_allows_matching_config_on_restart(
    tmp_path: object, session: Session
) -> None:
    settings = _fake_settings(str(tmp_path))
    check_embedding_space(settings, dimension=16, session=session)
    # Simulates a second process startup with the same config -> must not raise.
    check_embedding_space(settings, dimension=16, session=session)


def test_build_providers_end_to_end_guard_then_reject_change(
    tmp_path: object, session: Session
) -> None:
    settings = _fake_settings(str(tmp_path))
    build_providers(settings, session=session)

    changed = settings.model_copy(
        update={"embeddings": settings.embeddings.model_copy(update={"model": "different-model"})}
    )
    with pytest.raises(ConfigError, match="embedding configuration changed"):
        build_providers(changed, session=session)
