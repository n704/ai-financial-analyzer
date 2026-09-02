"""Config → concrete provider adapters (P1.3, P6.1).

The one place that maps a config string (``llm.provider``, ``embeddings.provider``,
``vector_store.provider``, ``market_data.provider``, ``forecast.provider``) to a
concrete class — core code asks for a
:class:`~app.providers.base.LLMProvider` etc. and never branches on a provider
name itself (ARCHITECTURE.md §3). Vendor SDK imports are deferred into each
``_build_*`` branch so selecting the fake profile never requires
``google-genai``, ``psycopg``, or any other extra to be installed.

Also owns the embedding-space startup guard: comparing the configured embedding
provider/model/dimension against the persisted ``index_meta`` row before the
vector store is used for anything (ARCHITECTURE.md §3, "Embedding-space guard") —
and its F6 sibling, the forecast boot checks: the weights-license gate, the
"``forecast`` extra is importable" check, and ``max_context``/``max_horizon``
against the adapter's reported limits. All three fail at startup, none at
request time (ARCHITECTURE.md §3, "Forecast weights & the license guard").
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import ConfigError, Settings
from app.db.repositories import IndexMetaRepository
from app.domain.forecast import season_length_for_interval
from app.providers.base import (
    EmbeddingProvider,
    ForecastProvider,
    LLMProvider,
    MarketDataProvider,
    UsageSink,
    VectorStore,
)


@dataclass(frozen=True, slots=True)
class ForecastProviders:
    """The F6 pair — a data source and a model, kept separate so either can be
    swapped alone (ARCHITECTURE.md §3). Present only where forecast jobs run:
    the API process in single-process mode, the worker when scaled."""

    market_data: MarketDataProvider
    forecast: ForecastProvider


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    """The full provider set, built once at startup and injected everywhere.
    ``forecasting`` is ``None`` when ``forecast.enabled`` is false or when this
    process only enqueues forecast jobs (the arq worker holds the model)."""

    llm: LLMProvider
    embeddings: EmbeddingProvider
    vector_store: VectorStore
    forecasting: ForecastProviders | None = None


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


# --------------------------------------------------------------------------- #
# F6: market data + forecasting (P6.1 boot checks live here)
# --------------------------------------------------------------------------- #
def build_market_data_provider(settings: Settings) -> MarketDataProvider:
    cfg = settings.market_data
    if cfg.provider == "fixture":
        from app.providers.marketdata.fixture import FixtureMarketDataProvider

        known = cfg.options.get("known_tickers")
        return FixtureMarketDataProvider(
            seed=int(cfg.options.get("seed", 0)),
            known_tickers=[str(t) for t in known] if known is not None else None,
        )

    if cfg.provider == "stooq":
        from app.providers.marketdata.stooq import StooqMarketDataProvider

        return StooqMarketDataProvider(
            symbol_suffix=str(cfg.options.get("symbol_suffix", ".us")),
            timeout_s=float(cfg.options.get("timeout_s", 15.0)),
        )

    raise ConfigError(
        f"market_data.provider={cfg.provider!r} is not implemented yet "
        f"(supported now: fixture, stooq; yfinance/alphavantage/tiingo reserved)"
    )


def check_market_data_capabilities(settings: Settings, provider: MarketDataProvider) -> None:
    if settings.market_data.is_intraday and not provider.supports_intraday:
        raise ConfigError(
            f"market_data.interval={settings.market_data.interval!r} is intraday, but "
            f"market_data.provider={provider.provider!r} reports supports_intraday=False"
        )


def _require_forecast_extra() -> None:
    """Boot check #2: ``forecast.provider: timesfm`` needs the ``forecast`` extra.
    Checked before any weight download is attempted so a missing dependency
    reads as a config error, not a stack trace from inside the adapter."""
    try:
        import timesfm  # noqa: F401
    except ImportError as exc:
        raise ConfigError(
            "forecast.enabled=true with forecast.provider='timesfm' requires the "
            "`forecast` extra (`uv sync --extra forecast` installs timesfm[torch]), "
            f"which is not importable: {exc}"
        ) from exc


def build_forecast_provider(settings: Settings) -> ForecastProvider:
    cfg = settings.forecast
    if cfg.provider == "naive":
        from app.providers.forecast.naive import NaiveForecastProvider

        return NaiveForecastProvider(
            method=str(cfg.options.get("method", "drift")),
            season_length=season_length_for_interval(settings.market_data.interval),
        )

    if cfg.provider == "fake":
        from app.providers.forecast.fake import FakeForecastProvider

        return FakeForecastProvider(max_context=cfg.max_context, max_horizon=cfg.max_horizon)

    if cfg.provider == "timesfm":
        from app.providers.forecast.licenses import check_weights_license

        # Boot check #1 — the license gate — runs before the import check and
        # long before `from_pretrained`: restricted weights are refused without
        # touching the network.
        check_weights_license(cfg.model, ack=cfg.weights_license_ack)
        _require_forecast_extra()

        from app.providers.forecast.timesfm import TimesFMForecastProvider

        return TimesFMForecastProvider(
            model=cfg.model,
            revision=cfg.revision,
            device=cfg.device,
            max_context=cfg.max_context,
            max_horizon=cfg.max_horizon,
            quantiles=cfg.quantiles,
            torch_compile=bool(cfg.options.get("torch_compile", False)),
            normalize_inputs=bool(cfg.options.get("normalize_inputs", True)),
            local_files_only=bool(cfg.options.get("local_files_only", False)),
            cache_dir=(
                str(cfg.options["cache_dir"]) if cfg.options.get("cache_dir") is not None else None
            ),
        )

    raise ConfigError(
        f"forecast.provider={cfg.provider!r} is not implemented yet "
        f"(supported now: naive, fake, timesfm)"
    )


def check_forecast_limits(settings: Settings, provider: ForecastProvider) -> None:
    """Boot check #3: the configured window/horizon must fit the adapter's
    reported limits, so a request can never ask the model for more than it
    was compiled for."""
    cfg = settings.forecast
    if cfg.max_context > provider.max_context:
        raise ConfigError(
            f"forecast.max_context={cfg.max_context} exceeds the "
            f"{provider.provider!r} adapter's limit of {provider.max_context}"
        )
    if cfg.max_horizon > provider.max_horizon:
        raise ConfigError(
            f"forecast.max_horizon={cfg.max_horizon} exceeds the "
            f"{provider.provider!r} adapter's limit of {provider.max_horizon}"
        )
    if settings.limits.max_forecast_horizon > provider.max_horizon:
        raise ConfigError(
            f"limits.max_forecast_horizon={settings.limits.max_forecast_horizon} exceeds "
            f"the {provider.provider!r} adapter's limit of {provider.max_horizon}"
        )


def build_forecast_providers(settings: Settings) -> ForecastProviders | None:
    """Build the F6 pair when ``forecast.enabled`` — running every boot check
    — or return ``None`` when forecasting is off. Loads the model (resident
    for the process lifetime); call it only in the process that drains the
    queue."""
    if not settings.forecast.enabled:
        return None
    market_data = build_market_data_provider(settings)
    check_market_data_capabilities(settings, market_data)
    forecast = build_forecast_provider(settings)
    check_forecast_limits(settings, forecast)
    return ForecastProviders(market_data=market_data, forecast=forecast)


def build_providers(
    settings: Settings,
    *,
    session: Session,
    usage_sink: UsageSink | None = None,
    include_forecasting: bool = True,
) -> ProviderBundle:
    """Build the full provider set once at startup, running the embedding-space
    guard before the vector store is constructed for anything else to use.

    ``include_forecasting=False`` skips the F6 providers — used by API replicas
    in the scaled profile, where the arq worker holds the resident model and
    the API only enqueues (ARCHITECTURE.md §2).
    """
    llm = build_llm_provider(settings, usage_sink=usage_sink)
    embeddings = build_embedding_provider(settings, usage_sink=usage_sink)
    check_embedding_space(settings, dimension=embeddings.dimension, session=session)
    vector_store = build_vector_store(settings, embedding_dimension=embeddings.dimension)
    forecasting = build_forecast_providers(settings) if include_forecasting else None
    return ProviderBundle(
        llm=llm, embeddings=embeddings, vector_store=vector_store, forecasting=forecasting
    )
