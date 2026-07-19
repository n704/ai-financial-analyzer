"""Config → concrete provider adapters (P1.3).

The one place that maps a config string (``llm.provider``, ``embeddings.provider``,
``vector_store.provider``) to a concrete class — core code asks for a
:class:`~app.providers.base.LLMProvider` etc. and never branches on a provider
name itself (ARCHITECTURE.md §3). Vendor SDK imports are deferred into each
``_build_*`` branch so selecting the fake profile never requires
``google-genai``, ``psycopg``, or any other extra to be installed.

Also owns the embedding-space startup guard: comparing the configured embedding
provider/model/dimension against the persisted ``index_meta`` row before the
vector store is used for anything (ARCHITECTURE.md §3, "Embedding-space guard").
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import ConfigError, Settings
from app.db.repositories import IndexMetaRepository
from app.providers.base import EmbeddingProvider, LLMProvider, UsageSink, VectorStore


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    """The full provider set, built once at startup and injected everywhere."""

    llm: LLMProvider
    embeddings: EmbeddingProvider
    vector_store: VectorStore


def build_llm_provider(settings: Settings, *, usage_sink: UsageSink | None = None) -> LLMProvider:
    cfg = settings.llm
    if cfg.provider == "fake":
        from app.providers.llm.fake import FakeLLMProvider

        return FakeLLMProvider(model=cfg.model)

    if cfg.provider == "gemini":
        from app.providers.llm.gemini import GeminiLLMProvider

        api_key = cfg.resolve_api_key()
        if api_key is None:
            raise ConfigError("llm.provider='gemini' requires api_key_env to be set")
        return GeminiLLMProvider(
            api_key=api_key.get_secret_value(),
            model=cfg.model,
            options=cfg.options,
            usage_sink=usage_sink,
        )

    raise ConfigError(
        f"llm.provider={cfg.provider!r} is not implemented yet "
        f"(supported now: fake, gemini; anthropic/openai/ollama land in P5.1)"
    )


def build_embedding_provider(
    settings: Settings, *, usage_sink: UsageSink | None = None
) -> EmbeddingProvider:
    cfg = settings.embeddings
    if cfg.provider == "fake":
        from app.providers.embeddings.fake import FakeEmbeddingProvider

        dimension = int(cfg.options.get("dimension", 16))
        return FakeEmbeddingProvider(model=cfg.model, dimension=dimension)

    if cfg.provider == "gemini":
        from app.providers.embeddings.gemini import GeminiEmbeddingProvider

        api_key = cfg.resolve_api_key()
        if api_key is None:
            raise ConfigError("embeddings.provider='gemini' requires api_key_env to be set")
        dimension = int(cfg.options.get("dimension", 3072))
        return GeminiEmbeddingProvider(
            api_key=api_key.get_secret_value(),
            model=cfg.model,
            dimension=dimension,
            usage_sink=usage_sink,
        )

    raise ConfigError(
        f"embeddings.provider={cfg.provider!r} is not implemented yet "
        f"(supported now: fake, gemini; voyage/openai/local land in P5.2)"
    )


def build_vector_store(settings: Settings, *, embedding_dimension: int) -> VectorStore:
    cfg = settings.vector_store
    if cfg.provider == "chroma":
        from app.providers.vectorstores.chroma import ChromaVectorStore

        if not cfg.path:
            raise ConfigError("vector_store.provider='chroma' requires vector_store.path")
        return ChromaVectorStore(path=cfg.path, collection=cfg.collection)

    if cfg.provider == "pgvector":
        from app.db.base import build_engine
        from app.providers.vectorstores.pgvector import PgVectorStore

        engine = build_engine(settings.database.url)
        return PgVectorStore(engine=engine, dimension=embedding_dimension)

    raise ConfigError(
        f"vector_store.provider={cfg.provider!r} is not implemented yet "
        f"(supported now: chroma, pgvector; qdrant/faiss reserved)"
    )


def check_embedding_space(settings: Settings, *, dimension: int, session: Session) -> None:
    """Compare the configured embedding provider/model/dimension against the
    persisted ``index_meta`` row. No row yet (first run) → record it. Mismatch
    → hard error naming the explicit re-index path — vectors from different
    embedding spaces are never mixed silently.
    """
    repo = IndexMetaRepository(session)
    existing = repo.get()
    if existing is None:
        repo.set(
            embedding_provider=settings.embeddings.provider,
            embedding_model=settings.embeddings.model,
            dimension=dimension,
        )
        session.commit()
        return

    configured = (settings.embeddings.provider, settings.embeddings.model, dimension)
    persisted = (existing.embedding_provider, existing.embedding_model, existing.dimension)
    if configured != persisted:
        raise ConfigError(
            "embedding configuration changed since the index was built: "
            f"configured provider/model/dimension={configured!r} != "
            f"index_meta={persisted!r}. Vectors from different embedding spaces "
            "are never mixed silently — re-run ingestion via the `reindex` "
            "command (P5.2) before starting with this config."
        )


def build_providers(
    settings: Settings,
    *,
    session: Session,
    usage_sink: UsageSink | None = None,
) -> ProviderBundle:
    """Build the full provider set once at startup, running the embedding-space
    guard before the vector store is constructed for anything else to use."""
    llm = build_llm_provider(settings, usage_sink=usage_sink)
    embeddings = build_embedding_provider(settings, usage_sink=usage_sink)
    check_embedding_space(settings, dimension=embeddings.dimension, session=session)
    vector_store = build_vector_store(settings, embedding_dimension=embeddings.dimension)
    return ProviderBundle(llm=llm, embeddings=embeddings, vector_store=vector_store)
