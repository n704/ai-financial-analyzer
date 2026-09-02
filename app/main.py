"""FastAPI application factory (P1.13).

Wires config → DB engine/session factory → provider bundle (with the
embedding-space guard and, when ``forecast.enabled``, the forecast boot
checks) → infra bundle → object storage → auth, and exposes auth + document +
forecast routes plus ``/healthz``/``/readyz``. On the default ``inprocess``
queue backend, ingestion (P2.1) and forecast (P6.6) jobs are registered and
run inline in this process; on ``arq``, the separate ``app.worker`` process
runs them instead (same job bodies) and holds the resident forecast model, so
this process skips loading it.
"""

from __future__ import annotations

import functools
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.engine import make_url

from app import __version__
from app.api import documents, forecasts, ops
from app.api.auth.router import router as auth_router
from app.api.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.api.state import AppState
from app.config import Settings, load_settings
from app.db.base import build_engine, build_session_factory, session_scope
from app.infra import build_infra
from app.infra.queue import InProcessQueue
from app.logging import configure_logging
from app.providers import build_providers
from app.services.forecasting import run_forecast_job
from app.services.jobs import (
    FORECAST_JOB,
    INGEST_DOCUMENT_JOB,
    ForecastRuntime,
    JobContext,
    run_ingest_document,
)
from app.storage import build_object_storage

log = structlog.get_logger()

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _maybe_migrate_sqlite(database_url: str) -> None:
    """Auto-apply migrations for the zero-ops SQLite default profile, so
    ``make run`` works with no separate release step. Postgres (scaled
    profile) is migrated as an explicit release step instead
    (ARCHITECTURE.md §7) — the app never auto-migrates a shared database.
    """
    if not database_url.startswith("sqlite"):
        return

    # SQLite (unlike a real server) won't create the parent directory of its
    # file for you — a fresh checkout's `./data/...` doesn't exist yet.
    db_path = make_url(database_url).database
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "app" / "db" / "migrations"))
    cfg.cmd_opts = type("Opts", (), {"x": [f"db_url={database_url}"]})()
    command.upgrade(cfg, "head")


def _validate_secrets_eagerly(settings: Settings) -> None:
    """Fail fast on missing secrets at startup rather than on the first
    request that happens to need them (P1.1's "invalid config fails fast")."""
    settings.auth.resolve_secret()
    if settings.object_storage.provider == "local":
        settings.object_storage.resolve_signing_secret()
    settings.llm.resolve_api_key()
    settings.embeddings.resolve_api_key()
    if settings.forecast.enabled:
        settings.market_data.resolve_api_key()


async def _build_app_state(settings: Settings) -> AppState:
    _validate_secrets_eagerly(settings)
    _maybe_migrate_sqlite(settings.database.url)

    engine = build_engine(settings.database.url)
    session_factory = build_session_factory(engine)

    with session_scope(session_factory) as session:
        # The forecast model is resident in whichever process drains the
        # queue: this one in single-process mode, the arq worker when scaled —
        # API replicas there only enqueue, so they skip loading ~1 GB of weights.
        providers = build_providers(
            settings, session=session, include_forecasting=not settings.is_multiprocess
        )

    infra = await build_infra(settings)
    storage = build_object_storage(settings)

    if isinstance(infra.queue, InProcessQueue):
        # Single-process mode: jobs run inline in this process's event loop
        # (ARCHITECTURE.md §2). On `queue.backend: arq`, `app.worker` registers
        # the same job bodies instead — this process only enqueues.
        forecasting = (
            ForecastRuntime(
                market_data=providers.forecasting.market_data,
                forecast=providers.forecasting.forecast,
                settings=settings,
            )
            if providers.forecasting is not None
            else None
        )
        job_ctx = JobContext(
            session_factory=session_factory, events=infra.events, forecasting=forecasting
        )
        infra.queue.register(INGEST_DOCUMENT_JOB, functools.partial(run_ingest_document, job_ctx))
        infra.queue.register(FORECAST_JOB, functools.partial(run_forecast_job, job_ctx))

    return AppState(
        settings=settings,
        session_factory=session_factory,
        providers=providers,
        infra=infra,
        storage=storage,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    app.state.app_state = await _build_app_state(settings)
    forecasting = app.state.app_state.providers.forecasting
    log.info(
        "app.startup",
        llm_provider=app.state.app_state.providers.llm.provider,
        database=settings.database.url,
        forecast_enabled=settings.forecast.enabled,
        forecast_provider=forecasting.forecast.provider if forecasting else None,
    )
    yield
    log.info("app.shutdown")


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="AI Financial Analyzer", version=__version__, lifespan=_lifespan)

    # Added in this order so RequestContextMiddleware ends up outermost (see
    # its module docstring) — every log line, including a 429 from the rate
    # limiter, carries the request id.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(ops.router)
    app.include_router(auth_router)
    app.include_router(documents.router)
    app.include_router(forecasts.router)

    return app


app = create_app()
