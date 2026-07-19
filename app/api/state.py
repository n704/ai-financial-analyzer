"""Everything built once at startup and shared across requests (P1.13).

Assembled in ``app/main.py``'s lifespan and stashed on ``app.state.app_state``;
FastAPI dependencies (``app/api/dependencies.py``) read it back per request.
Kept as one small dataclass rather than scattering globals so tests can build
one directly without booting the whole app.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.infra import InfraBundle
from app.providers import ProviderBundle
from app.storage import ObjectStorage


@dataclass(slots=True)
class AppState:
    settings: Settings
    session_factory: sessionmaker[Session]
    providers: ProviderBundle
    infra: InfraBundle
    storage: ObjectStorage
