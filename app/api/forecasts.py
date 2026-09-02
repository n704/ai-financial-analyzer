"""Forecast endpoints (P6.6, P6.7): ``POST/GET /forecasts``,
``GET/DELETE /forecasts/{id}``, the SSE progress stream, and
``POST /forecasts/{id}/narrate``.

Every response that carries a forecast carries *all* of it — median path,
quantile band, backtest scorecard, skill verdict, provenance, disclaimer —
because the response model has no shape for a bare point path (SPEC.md §3.6,
"Never a bare point estimate"). Every lookup goes through the user-scoped
``ForecastRepository``; there is no path from an id alone to a row.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.api.dependencies import get_app_state, get_current_user, get_db_session
from app.api.state import AppState
from app.db.models import Forecast, User
from app.db.repositories import DocumentRepository, ForecastRepository
from app.domain.forecast import DISCLAIMER_TEXT, InvalidTicker, future_trading_days
from app.providers.base import ProviderError, ProviderRateLimited, ProviderUnavailable
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
    request_forecast,
)
from app.services.jobs import forecast_channel

router = APIRouter(prefix="/api/v1/forecasts", tags=["forecasts"])

_TERMINAL_STATUSES = {"ready", "failed"}


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class ForecastCreateRequest(BaseModel):
    ticker: str | None = Field(default=None, max_length=20)
    document_id: str | None = None
    horizon: int = Field(ge=1, description="Forecast horizon in bars (trading days for 1d).")
    interval: str | None = Field(default=None, max_length=10)


class NarrateRequest(BaseModel):
    focus: str | None = Field(default=None, max_length=500)


class Provenance(BaseModel):
    provider: str
    model: str
    checkpoint_revision: str
    source: str
    as_of: dt.date
    transform: str
    context_start: dt.date | None
    context_end: dt.date | None
    context_length: int | None
    generated_at: dt.datetime | None


class Disclaimer(BaseModel):
    version: int
    text: str


class ForecastSummary(BaseModel):
    id: str
    status: str
    stage: str | None
    error: str | None
    ticker: str
    document_id: str | None
    interval: str
    horizon: int
    skill: str | None
    skill_score: float | None
    created_at: dt.datetime


class ForecastArtifactResponse(ForecastSummary):
    """The full artifact. ``median`` is the 0.5 quantile path; ``point`` is the
    provider's point path (they coincide for most providers). ``quantiles``
    is one path per entry of ``quantile_levels``."""

    dates: list[dt.date] | None
    point: list[float] | None
    median: list[float] | None
    quantile_levels: list[float] | None
    quantiles: list[list[float]] | None
    band_source: str | None
    backtest: dict[str, object] | None
    provenance: Provenance
    disclaimer: Disclaimer


def _summary(row: Forecast) -> ForecastSummary:
    return ForecastSummary(
        id=row.id,
        status=row.status,
        stage=row.stage,
        error=row.error,
        ticker=row.ticker,
        document_id=row.document_id,
        interval=row.interval,
        horizon=row.horizon,
        skill=row.skill,
        skill_score=row.skill_score,
        created_at=row.created_at,
    )


def _artifact(row: Forecast) -> ForecastArtifactResponse:
    median: list[float] | None = None
    if row.quantile_levels and row.quantiles:
        for level, path in zip(row.quantile_levels, row.quantiles, strict=True):
            if abs(level - 0.5) < 1e-9:
                median = list(path)
    dates = (
        future_trading_days(row.context_end, row.horizon)
        if row.status == "ready" and row.context_end is not None
        else None
    )
    return ForecastArtifactResponse(
        **_summary(row).model_dump(),
        dates=dates,
        point=row.point,
        median=median,
        quantile_levels=row.quantile_levels,
        quantiles=row.quantiles,
        band_source=row.band_source,
        backtest=row.backtest,
        provenance=Provenance(
            provider=row.provider,
            model=row.model,
            checkpoint_revision=row.checkpoint_revision,
            source=row.source,
            as_of=row.as_of,
            transform=row.transform,
            context_start=row.context_start,
            context_end=row.context_end,
            context_length=row.context_length,
            generated_at=row.completed_at,
        ),
        disclaimer=Disclaimer(version=row.disclaimer_version, text=DISCLAIMER_TEXT),
    )


def _load_owned(forecast_id: str, user: User, session: Session) -> Forecast:
    row = ForecastRepository(session).get(forecast_id=forecast_id, user_id=user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="forecast not found")
    return row


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.post("", response_model=ForecastArtifactResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_forecast(
    body: ForecastCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    state: Annotated[AppState, Depends(get_app_state)],
) -> StreamingResponse | ForecastArtifactResponse:
    """Queue a forecast (202) — or return the identical, still-fresh artifact
    (200) when one exists (SPEC.md §3.6 step 5). Progress streams from
    ``GET /forecasts/{id}/events``."""
    try:
        outcome = await request_forecast(
            user=current_user,
            request=ForecastRequest(
                horizon=body.horizon,
                ticker=body.ticker,
                document_id=body.document_id,
                interval=body.interval,
            ),
            session=session,
            queue=state.infra.queue,
            settings=state.settings,
        )
    except ForecastingDisabled as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except DocumentNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (InvalidTicker, InvalidForecastRequest, DocumentHasNoTicker, HorizonTooLong) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except ForecastQuotaExceeded as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    artifact = _artifact(outcome.forecast)
    if outcome.created:
        return artifact
    return StreamingResponse(
        iter([artifact.model_dump_json()]),
        status_code=status.HTTP_200_OK,
        media_type="application/json",
    )


@router.get("", response_model=list[ForecastSummary])
def list_forecasts(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    ticker: Annotated[str | None, Query(max_length=20)] = None,
    document_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ForecastSummary]:
    rows = ForecastRepository(session).list_for_user(
        user_id=current_user.id,
        ticker=ticker.strip().upper() if ticker else None,
        document_id=document_id,
        limit=limit,
        offset=offset,
    )
    return [_summary(row) for row in rows]


@router.get("/{forecast_id}", response_model=ForecastArtifactResponse)
def get_forecast(
    forecast_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ForecastArtifactResponse:
    return _artifact(_load_owned(forecast_id, current_user, session))


@router.delete("/{forecast_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_forecast(
    forecast_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> None:
    if not ForecastRepository(session).delete(forecast_id=forecast_id, user_id=current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="forecast not found")
    session.commit()


@router.get("/{forecast_id}/events")
async def forecast_events(
    forecast_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    state: Annotated[AppState, Depends(get_app_state)],
) -> StreamingResponse:
    """SSE progress, same shape as the document stream: an immediate status
    snapshot, then live events until a terminal status."""
    row = _load_owned(forecast_id, current_user, session)
    channel = forecast_channel(forecast_id)
    initial: dict[str, object] = {"status": row.status, "stage": row.stage}
    if row.status == "ready":
        initial.update({"skill": row.skill, "skill_score": row.skill_score})
    if row.status == "failed":
        initial["error"] = row.error

    async def event_stream() -> AsyncIterator[str]:
        stream = await state.infra.events.subscribe(channel)
        yield _sse_frame(initial)
        if initial["status"] in _TERMINAL_STATUSES:
            return
        async for event in stream:
            yield _sse_frame(event)
            if event.get("status") in _TERMINAL_STATUSES:
                return

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{forecast_id}/narrate")
def narrate(
    forecast_id: str,
    body: NarrateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    state: Annotated[AppState, Depends(get_app_state)],
) -> StreamingResponse:
    """Descriptive narrative over the computed table (SPEC.md §3.6 step 6),
    streamed as SSE ``token`` frames and a final ``done`` frame carrying the
    ``forecast:{id}`` citation. Advice-seeking prompts are refused with 422
    before any model call."""
    row = _load_owned(forecast_id, current_user, session)
    document = (
        DocumentRepository(session).get(document_id=row.document_id, user_id=current_user.id)
        if row.document_id
        else None
    )
    try:
        tokens = narrate_forecast(
            forecast=row, document=document, llm=state.providers.llm, focus=body.focus
        )
    except AdviceRequestRefused as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except ForecastNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def frames() -> Iterator[str]:
        try:
            for token in tokens:
                yield _sse_frame({"type": "token", "text": token})
        except ProviderRateLimited as exc:
            yield _sse_frame({"type": "error", "status": 429, "detail": str(exc)})
            return
        except ProviderUnavailable as exc:
            yield _sse_frame({"type": "error", "status": 503, "detail": str(exc)})
            return
        except ProviderError as exc:
            yield _sse_frame({"type": "error", "status": 422, "detail": str(exc)})
            return
        yield _sse_frame({"type": "done", "citation": f"forecast:{row.id}"})

    return StreamingResponse(frames(), media_type="text/event-stream")


def _sse_frame(event: Mapping[str, object]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"
