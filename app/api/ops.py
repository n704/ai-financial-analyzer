"""Ops endpoints (P1.13): liveness + readiness (SPEC.md §5).

``/healthz`` is a pure liveness check (no dependency I/O) so an overloaded or
degraded-but-alive process still reports "up" — orchestrators use this to
decide whether to restart the container, not whether to route traffic to it.
``/readyz`` actually exercises the DB, vector store, and (only when the config
selects it) Redis, and is what load balancers / orchestrators use to gate
traffic.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.api.dependencies import get_app_state
from app.api.state import AppState

router = APIRouter(tags=["ops"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Dependency checks live in /readyz."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(state: Annotated[AppState, Depends(get_app_state)]) -> dict[str, str]:
    checks: dict[str, str] = {}

    try:
        with state.session_factory() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    try:
        dimension = state.providers.embeddings.dimension
        state.providers.vector_store.query(
            [0.0] * dimension, k=1, filters={"user_id": "__readyz__"}
        )
        checks["vector_store"] = "ok"
    except Exception as exc:
        checks["vector_store"] = f"error: {exc}"

    # The config-coherence guard (app/config/models.py) guarantees that any
    # backend requiring Redis (queue=arq, events=redis) also sets
    # cache.backend=redis, so checking the cache backend alone is sufficient
    # to know whether Redis is in play at all.
    if state.settings.cache.backend == "redis":
        try:
            ok = await state.infra.cache.ping()
            checks["redis"] = "ok" if ok else "error: ping returned falsy"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"

    if any(v.startswith("error") for v in checks.values()):
        raise HTTPException(status_code=503, detail=checks)
    return checks
