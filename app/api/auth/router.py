"""Auth routes (P1.13): register/login/refresh/logout, delete account, and a
minimal ``/me`` route that exercises the ``get_current_user`` dependency end
to end (PLAN.md P1.13 "done when": an authenticated request reaches a
protected route; unauth is rejected).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth.schemas import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.api.auth.service import (
    AuthService,
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRefreshToken,
)
from app.api.dependencies import get_current_user, get_db_session, get_settings
from app.config import Settings
from app.db.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class MeResponse(BaseModel):
    id: str
    email: str


def _service(session: Session, settings: Settings) -> AuthService:
    return AuthService(session=session, auth_config=settings.auth)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    try:
        tokens = _service(session, settings).register(
            email=payload.email, password=payload.password
        )
    except EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        ) from exc
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    try:
        tokens = _service(session, settings).login(email=payload.email, password=payload.password)
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password"
        ) from exc
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    payload: RefreshRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    try:
        tokens = _service(session, settings).refresh(refresh_token=payload.refresh_token)
    except InvalidRefreshToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token"
        ) from exc
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: LogoutRequest,
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Idempotent: an unknown/already-revoked token is a silent no-op — logout
    always succeeds from the caller's point of view."""
    _service(session, settings).logout(refresh_token=payload.refresh_token)


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    _service(session, settings).delete_account(user_id=current_user.id)


@router.get("/me", response_model=MeResponse)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(id=current_user.id, email=current_user.email)
