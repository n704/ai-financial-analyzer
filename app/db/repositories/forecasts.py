"""Forecast repository — user-scoped CRUD over ``forecasts`` (P6.6).

Same convention as ``DocumentRepository``: every read and write takes and
filters on ``user_id``. The cross-tenant denial tests for the forecast
endpoints rely on there being no other path to a row.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from app.db.base import new_uuid, utcnow
from app.db.models import Forecast
from app.db.repositories.base import ScopedRepository


class ForecastRepository(ScopedRepository):
    def create(
        self,
        *,
        user_id: str,
        ticker: str,
        interval: str,
        horizon: int,
        transform: str,
        provider: str,
        model: str,
        checkpoint_revision: str,
        source: str,
        as_of: dt.date,
        input_hash: str,
        disclaimer_version: int,
        document_id: str | None = None,
        forecast_id: str | None = None,
    ) -> Forecast:
        row = Forecast(
            id=forecast_id or new_uuid(),
            user_id=user_id,
            document_id=document_id,
            ticker=ticker,
            interval=interval,
            horizon=horizon,
            transform=transform,
            provider=provider,
            model=model,
            checkpoint_revision=checkpoint_revision,
            source=source,
            as_of=as_of,
            input_hash=input_hash,
            disclaimer_version=disclaimer_version,
            status="queued",
            stage=None,
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get(self, *, forecast_id: str, user_id: str) -> Forecast | None:
        stmt = select(Forecast).where(Forecast.id == forecast_id, Forecast.user_id == user_id)
        return self.session.scalar(stmt)

    def get_by_input_hash(self, *, user_id: str, input_hash: str) -> Forecast | None:
        stmt = select(Forecast).where(
            Forecast.user_id == user_id, Forecast.input_hash == input_hash
        )
        return self.session.scalar(stmt)

    def list_for_user(
        self,
        *,
        user_id: str,
        ticker: str | None = None,
        document_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Forecast]:
        stmt = select(Forecast).where(Forecast.user_id == user_id)
        if ticker is not None:
            stmt = stmt.where(Forecast.ticker == ticker)
        if document_id is not None:
            stmt = stmt.where(Forecast.document_id == document_id)
        stmt = stmt.order_by(Forecast.created_at.desc()).limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    def count_created_since(self, *, user_id: str, since: dt.datetime) -> int:
        """Daily-quota check: forecasts this user has *requested* since
        ``since`` (dedupe hits don't create rows, so they don't count)."""
        stmt = (
            select(func.count())
            .select_from(Forecast)
            .where(Forecast.user_id == user_id, Forecast.created_at >= since)
        )
        return int(self.session.scalar(stmt) or 0)

    def update_status(
        self,
        *,
        forecast_id: str,
        user_id: str,
        status: str,
        stage: str | None = None,
        error: str | None = None,
    ) -> None:
        row = self.get(forecast_id=forecast_id, user_id=user_id)
        if row is not None:
            row.status = status
            row.stage = stage
            row.error = error
            if status in ("ready", "failed"):
                row.completed_at = utcnow()
            self.session.flush()

    def reset_for_rerun(self, *, forecast_id: str, user_id: str) -> Forecast | None:
        """Re-queue an existing artifact in place (same id, same URL) — used
        when a dedupe hit is older than ``forecast.cache_ttl_s`` or failed."""
        row = self.get(forecast_id=forecast_id, user_id=user_id)
        if row is None:
            return None
        row.status = "queued"
        row.stage = None
        row.error = None
        row.point = None
        row.quantile_levels = None
        row.quantiles = None
        row.band_source = None
        row.backtest = None
        row.skill = None
        row.skill_score = None
        row.context_start = None
        row.context_end = None
        row.context_length = None
        row.completed_at = None
        row.created_at = utcnow()
        self.session.flush()
        return row

    def store_result(
        self,
        *,
        forecast_id: str,
        user_id: str,
        context_start: dt.date,
        context_end: dt.date,
        context_length: int,
        point: list[float],
        quantile_levels: list[float],
        quantiles: list[list[float]],
        band_source: str,
        backtest: dict[str, object],
        skill: str,
        skill_score: float | None,
    ) -> Forecast | None:
        row = self.get(forecast_id=forecast_id, user_id=user_id)
        if row is None:
            return None
        row.context_start = context_start
        row.context_end = context_end
        row.context_length = context_length
        row.point = point
        row.quantile_levels = quantile_levels
        row.quantiles = quantiles
        row.band_source = band_source
        row.backtest = backtest
        row.skill = skill
        row.skill_score = skill_score
        row.status = "ready"
        row.stage = None
        row.error = None
        row.completed_at = utcnow()
        self.session.flush()
        return row

    def delete(self, *, forecast_id: str, user_id: str) -> bool:
        row = self.get(forecast_id=forecast_id, user_id=user_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True


__all__ = ["ForecastRepository"]
