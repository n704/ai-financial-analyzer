"""P6.6/P6.7: the forecasting service against real in-memory infra — request
validation and dedupe, the queued job end-to-end on the dependency-free
``naive`` provider (the empirical-band path), readable failures, and the
narration guardrails."""

from __future__ import annotations

import asyncio
import datetime as dt
import functools
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.base import Base, build_engine, build_session_factory
from app.db.models import User
from app.db.repositories import DocumentRepository, ForecastRepository, UserRepository
from app.domain.forecast import SKILL_BETTER, SKILL_NO_BETTER, InvalidTicker
from app.infra.events import InProcessEventBus
from app.infra.queue import InProcessQueue
from app.providers.factory import build_forecast_providers
from app.providers.llm.fake import FakeLLMProvider
from app.services.forecasting import (
    AdviceRequestRefused,
    DocumentHasNoTicker,
    DocumentNotFound,
    ForecastingDisabled,
    ForecastNotReady,
    ForecastQuotaExceeded,
    ForecastRequest,
    HorizonTooLong,
    InvalidForecastRequest,
    narrate_forecast,
    render_forecast_table,
    request_forecast,
    run_forecast_job,
)
from app.services.jobs import FORECAST_JOB, ForecastRuntime, JobContext, forecast_channel


def _settings(**forecast_overrides: object) -> Settings:
    forecast: dict[str, object] = {
        "enabled": True,
        "provider": "naive",
        "max_context": 128,
        "max_horizon": 64,
        "transform": "log",
        "backtest_windows": 4,
        "cache_ttl_s": 3600,
    }
    forecast.update(forecast_overrides)
    return Settings.model_validate(
        {
            "llm": {"provider": "fake", "model": "fake-llm"},
            "embeddings": {"provider": "fake", "model": "fake-embedding"},
            "vector_store": {"provider": "chroma", "path": "./data/x"},
            "database": {"url": "sqlite:///:memory:"},
            "market_data": {
                "provider": "fixture",
                "max_history_days": 200,
                "options": {"seed": 11, "known_tickers": ["ACME", "WIDG"]},
            },
            "forecast": forecast,
            "limits": {"max_forecast_horizon": 20, "quotas": {"forecasts_per_day": 2}},
        }
    )


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    # A file, not `:memory:`: the job hops to a worker thread (asyncio.to_thread),
    # and SQLAlchemy hands each thread its own separate in-memory SQLite database.
    engine = build_engine(f"sqlite:///{tmp_path / 'svc.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def user(session: Session) -> User:
    u = UserRepository(session).create(email="alice@example.com", password_hash="h")
    session.commit()
    return u


class _Harness:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings) -> None:
        self.settings = settings
        self.events = InProcessEventBus()
        pair = build_forecast_providers(settings)
        assert pair is not None
        self.runtime = ForecastRuntime(
            market_data=pair.market_data, forecast=pair.forecast, settings=settings
        )
        self.job_ctx = JobContext(
            session_factory=session_factory, events=self.events, forecasting=self.runtime
        )
        self.queue = InProcessQueue()
        self.queue.register(FORECAST_JOB, functools.partial(run_forecast_job, self.job_ctx))


async def _drain() -> None:
    for _ in range(50):
        await asyncio.sleep(0.01)


async def test_request_validation(
    session: Session, user: User, session_factory: sessionmaker[Session]
) -> None:
    h = _Harness(session_factory, _settings())
    common = {"session": session, "queue": h.queue, "settings": h.settings, "user": user}

    with pytest.raises(ForecastingDisabled):
        await request_forecast(
            request=ForecastRequest(horizon=5, ticker="ACME"),
            **dict(common, settings=_settings(enabled=False)),  # type: ignore[arg-type]
        )
    with pytest.raises(InvalidForecastRequest):
        await request_forecast(request=ForecastRequest(horizon=5), **common)  # type: ignore[arg-type]
    with pytest.raises(InvalidTicker):
        await request_forecast(request=ForecastRequest(horizon=5, ticker="12"), **common)  # type: ignore[arg-type]
    with pytest.raises(HorizonTooLong):
        await request_forecast(request=ForecastRequest(horizon=21, ticker="ACME"), **common)  # type: ignore[arg-type]
    with pytest.raises(InvalidForecastRequest):
        await request_forecast(
            request=ForecastRequest(horizon=5, ticker="ACME", interval="daily"),
            **common,  # type: ignore[arg-type]
        )
    with pytest.raises(DocumentNotFound):
        await request_forecast(
            request=ForecastRequest(horizon=5, document_id="nope"),
            **common,  # type: ignore[arg-type]
        )
    doc = DocumentRepository(session).create(user_id=user.id, filename="a.pdf", storage_key="k")
    session.commit()
    with pytest.raises(DocumentHasNoTicker):
        await request_forecast(
            request=ForecastRequest(horizon=5, document_id=doc.id),
            **common,  # type: ignore[arg-type]
        )
    assert ForecastRepository(session).list_for_user(user_id=user.id) == []


async def test_job_end_to_end_on_naive_provider(
    session: Session, user: User, session_factory: sessionmaker[Session]
) -> None:
    h = _Harness(session_factory, _settings())
    stream = await h.events.subscribe(forecast_channel("__noop__"))  # exercise subscribe path
    assert stream is not None

    outcome = await request_forecast(
        user=user,
        request=ForecastRequest(horizon=5, ticker="acme"),
        session=session,
        queue=h.queue,
        settings=h.settings,
    )
    assert outcome.created is True
    assert outcome.forecast.status == "queued"
    assert outcome.forecast.ticker == "ACME"
    await _drain()

    with session_factory() as fresh:
        row = ForecastRepository(fresh).get(forecast_id=outcome.forecast.id, user_id=user.id)
        assert row is not None
        assert row.status == "ready", row.error
        assert row.provider == "naive" and row.model == "naive:drift"
        assert row.checkpoint_revision == "n/a" and row.source == "fixture"
        assert row.point is not None and len(row.point) == 5
        assert row.quantile_levels == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        assert row.quantiles is not None and len(row.quantiles) == 9
        assert row.band_source == "empirical"  # naive has no quantile head
        assert row.skill in (SKILL_BETTER, SKILL_NO_BETTER)
        assert row.backtest is not None and row.backtest["windows"] == 4
        assert {b["method"] for b in row.backtest["baselines"]} == {
            "last_value",
            "drift",
            "seasonal_naive",
        }
        assert row.context_end is not None and row.context_length == 128
        assert row.completed_at is not None

        # Identical request while fresh: the stored artifact, no new row.
        again = await request_forecast(
            user=user,
            request=ForecastRequest(horizon=5, ticker="ACME"),
            session=fresh,
            queue=h.queue,
            settings=h.settings,
        )
        assert again.created is False and again.forecast.id == row.id

        table = render_forecast_table(row)
        assert f"forecast_id={row.id}" in table and row.skill in table and "drift" in table


async def test_quota_counts_requests_not_dedupe_hits(
    session: Session, user: User, session_factory: sessionmaker[Session]
) -> None:
    h = _Harness(session_factory, _settings())
    for horizon in (3, 4):
        await request_forecast(
            user=user,
            request=ForecastRequest(horizon=horizon, ticker="ACME"),
            session=session,
            queue=h.queue,
            settings=h.settings,
        )
    with pytest.raises(ForecastQuotaExceeded):
        await request_forecast(
            user=user,
            request=ForecastRequest(horizon=5, ticker="ACME"),
            session=session,
            queue=h.queue,
            settings=h.settings,
        )
    await _drain()


async def test_failures_land_on_the_row_readably(
    session: Session, user: User, session_factory: sessionmaker[Session]
) -> None:
    h = _Harness(session_factory, _settings())
    not_found = await request_forecast(
        user=user,
        request=ForecastRequest(horizon=5, ticker="NOPE"),
        session=session,
        queue=h.queue,
        settings=h.settings,
    )
    await _drain()
    with session_factory() as fresh:
        row = ForecastRepository(fresh).get(forecast_id=not_found.forecast.id, user_id=user.id)
        assert row is not None and row.status == "failed"
        assert row.error is not None and "NOPE" in row.error

    # Too little history for the backtest: a domain error, also readable.
    short = _settings()
    short = short.model_copy(
        update={"market_data": short.market_data.model_copy(update={"max_history_days": 30})}
    )
    h2 = _Harness(session_factory, short)
    too_short = await request_forecast(
        user=user,
        request=ForecastRequest(horizon=10, ticker="WIDG"),
        session=session,
        queue=h2.queue,
        settings=h2.settings,
    )
    await _drain()
    with session_factory() as fresh:
        row = ForecastRepository(fresh).get(forecast_id=too_short.forecast.id, user_id=user.id)
        assert row is not None and row.status == "failed"
        assert row.error is not None and "bars" in row.error

    with pytest.raises(ForecastNotReady):
        render_forecast_table(row)


async def test_job_without_runtime_fails_instead_of_crashing(
    session: Session, user: User, session_factory: sessionmaker[Session]
) -> None:
    row = ForecastRepository(session).create(
        user_id=user.id,
        ticker="ACME",
        interval="1d",
        horizon=5,
        transform="log",
        provider="naive",
        model="x",
        checkpoint_revision="n/a",
        source="fixture",
        as_of=dt.date(2026, 9, 2),
        input_hash="a" * 64,
        disclaimer_version=1,
    )
    session.commit()
    job_ctx = JobContext(session_factory=session_factory, events=InProcessEventBus())
    await run_forecast_job(job_ctx, forecast_id=row.id, user_id=user.id)
    with session_factory() as fresh:
        stored = ForecastRepository(fresh).get(forecast_id=row.id, user_id=user.id)
        assert stored is not None and stored.status == "failed"
        assert stored.error is not None and "not enabled" in stored.error


async def test_narration_refuses_advice_and_streams_otherwise(
    session: Session, user: User, session_factory: sessionmaker[Session]
) -> None:
    h = _Harness(session_factory, _settings())
    outcome = await request_forecast(
        user=user,
        request=ForecastRequest(horizon=5, ticker="ACME"),
        session=session,
        queue=h.queue,
        settings=h.settings,
    )
    await _drain()
    with session_factory() as fresh:
        row = ForecastRepository(fresh).get(forecast_id=outcome.forecast.id, user_id=user.id)
        assert row is not None and row.status == "ready"
        llm = FakeLLMProvider()
        for focus in ("Should I buy this stock?", "give me a price target", "is it worth it"):
            with pytest.raises(AdviceRequestRefused):
                narrate_forecast(forecast=row, document=None, llm=llm, focus=focus)
        text = "".join(narrate_forecast(forecast=row, document=None, llm=llm, focus="margins"))
        assert text
