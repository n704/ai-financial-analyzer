"""FastAPI application factory.

P0 wires only the ops endpoints so the app (and its container health check) boots.
Auth, rate limiting, and feature routers are added from P1.12 onward.
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="AI Financial Analyzer", version=__version__)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    def readyz() -> dict[str, str]:
        """Readiness: dependency checks (DB, Redis, vector store) land in P1.12."""
        return {"status": "ready"}

    return app


app = create_app()
