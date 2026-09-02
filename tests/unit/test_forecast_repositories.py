"""P6.2/P6.6: the global (non-user-scoped) ``price_series`` cache and the
user-scoped ``forecasts`` repository — every forecast read/write filters on
``user_id``; the price cache deliberately has none."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base, build_engine, build_session_factory, utcnow
from app.db.repositories import (
    ForecastRepository,
    PriceSeriesRepository,
    UserRepository,
    to_price_series,
)
from app.providers.base import Bar, PriceSeries


@pytest.fixture
def session() -> Iterator[Session]:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = build_session_factory(engine)()
    try:
        yield s
    finally:
        s.close()


def _series(ticker: str = "ACME", n: int = 3) -> PriceSeries:
    bars = tuple(
        Bar(date=dt.date(2026, 1, 5) + dt.timedelta(days=i), open=1, high=2, low=0.5, close=1.5 + i)
        for i in range(n)
    )
    return PriceSeries(
        ticker=ticker, interval="1d", source="fixture", as_of=dt.date(2026, 2, 1), bars=bars
    )


def test_price_series_cache_put_get_replace_and_purge(session: Session) -> None:
    repo = PriceSeriesRepository(session)
    assert (
        repo.get(ticker="ACME", interval="1d", source="fixture", as_of=dt.date(2026, 2, 1)) is None
    )
    repo.put(_series())
    row = repo.get(ticker="ACME", interval="1d", source="fixture", as_of=dt.date(2026, 2, 1))
    assert row is not None
    assert to_price_series(row) == _series()

    repo.put(_series(n=5))  # same key: replaced, not duplicated
    row = repo.get(ticker="ACME", interval="1d", source="fixture", as_of=dt.date(2026, 2, 1))
    assert row is not None and len(row.bars) == 5

    assert repo.purge_fetched_before(utcnow() - dt.timedelta(days=1)) == 0
    assert repo.purge_fetched_before(utcnow() + dt.timedelta(seconds=1)) == 1


def _create(repo: ForecastRepository, user_id: str, **overrides: object):  # type: ignore[no-untyped-def]
    kwargs: dict[str, object] = {
        "user_id": user_id,
        "ticker": "ACME",
        "interval": "1d",
        "horizon": 10,
        "transform": "log",
        "provider": "naive",
        "model": "naive:drift",
        "checkpoint_revision": "n/a",
        "source": "fixture",
        "as_of": dt.date(2026, 9, 2),
        "input_hash": "h" * 64,
        "disclaimer_version": 1,
    }
    kwargs.update(overrides)
    return repo.create(**kwargs)  # type: ignore[arg-type]


def test_forecasts_are_user_scoped_everywhere(session: Session) -> None:
    users = UserRepository(session)
    alice = users.create(email="alice@example.com", password_hash="h")
    bob = users.create(email="bob@example.com", password_hash="h")
    repo = ForecastRepository(session)
    row = _create(repo, alice.id)
    session.commit()

    assert repo.get(forecast_id=row.id, user_id=alice.id) is not None
    assert repo.get(forecast_id=row.id, user_id=bob.id) is None
    assert repo.get_by_input_hash(user_id=bob.id, input_hash=row.input_hash) is None
    assert repo.list_for_user(user_id=bob.id) == []
    assert repo.list_for_user(user_id=alice.id, ticker="ACME")[0].id == row.id
    assert repo.list_for_user(user_id=alice.id, ticker="WIDG") == []
    assert repo.count_created_since(user_id=alice.id, since=utcnow() - dt.timedelta(hours=1)) == 1
    assert repo.count_created_since(user_id=bob.id, since=utcnow() - dt.timedelta(hours=1)) == 0

    repo.update_status(forecast_id=row.id, user_id=bob.id, status="failed", error="x")
    assert repo.get(forecast_id=row.id, user_id=alice.id).status == "queued"  # type: ignore[union-attr]
    assert (
        repo.store_result(
            forecast_id=row.id,
            user_id=bob.id,
            context_start=dt.date(2026, 1, 1),
            context_end=dt.date(2026, 9, 1),
            context_length=5,
            point=[1.0],
            quantile_levels=[0.5],
            quantiles=[[1.0]],
            band_source="empirical",
            backtest={},
            skill="no better than naive",
            skill_score=None,
        )
        is None
    )
    assert repo.delete(forecast_id=row.id, user_id=bob.id) is False
    assert repo.delete(forecast_id=row.id, user_id=alice.id) is True
    assert repo.get(forecast_id=row.id, user_id=alice.id) is None


def test_store_result_reset_and_same_hash_across_users(session: Session) -> None:
    users = UserRepository(session)
    alice = users.create(email="alice@example.com", password_hash="h")
    bob = users.create(email="bob@example.com", password_hash="h")
    repo = ForecastRepository(session)
    row = _create(repo, alice.id)
    _create(repo, bob.id)  # same input_hash, different user: allowed
    session.commit()

    stored = repo.store_result(
        forecast_id=row.id,
        user_id=alice.id,
        context_start=dt.date(2026, 1, 1),
        context_end=dt.date(2026, 9, 1),
        context_length=5,
        point=[1.0, 2.0],
        quantile_levels=[0.1, 0.5, 0.9],
        quantiles=[[0.5, 1.5], [1.0, 2.0], [1.5, 2.5]],
        band_source="provider",
        backtest={"windows": 2},
        skill="better than naive",
        skill_score=0.3,
    )
    assert stored is not None and stored.status == "ready" and stored.completed_at is not None

    reset = repo.reset_for_rerun(forecast_id=row.id, user_id=alice.id)
    assert reset is not None and reset.status == "queued" and reset.point is None
    assert reset.id == row.id

    with pytest.raises(IntegrityError):
        _create(repo, alice.id)  # duplicate (user_id, input_hash)
        session.flush()
