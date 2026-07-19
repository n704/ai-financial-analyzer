"""FastAPI dependencies (P1.13): app state, DB sessions, and current-user
resolution.

``get_current_user`` is this app's "auth middleware" in spirit — implemented as
a dependency rather than a blanket Starlette middleware, so public routes
(register/login/refresh) don't need per-path exemption logic; any route that
should require identity just adds ``Depends(get_current_user)``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.auth.service import AuthService, InvalidCredentials
from app.api.state import AppState
from app.config import Settings
from app.db.models import User

_bearer = HTTPBearer(auto_error=False)


def get_app_state(request: Request) -> AppState:
    state: AppState = request.app.state.app_state
    return state


def get_settings(state: Annotated[AppState, Depends(get_app_state)]) -> Settings:
    return state.settings


def get_db_session(state: Annotated[AppState, Depends(get_app_state)]) -> Iterator[Session]:
    """One session per request. Auth service methods commit themselves on
    success (each is a complete unit of work); this just guarantees the
    connection is released at the end of the request either way."""
    session = state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_db_session)],
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    service = AuthService(session=session, auth_config=settings.auth)
    try:
        user = service.get_current_user(access_token=credentials.credentials)
    except InvalidCredentials as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    # Every subsequent log line in this request now carries the user id
    # (ARCHITECTURE.md §6, "structlog JSON — request ID, user ID, route").
    structlog.contextvars.bind_contextvars(user_id=user.id)
    return user
