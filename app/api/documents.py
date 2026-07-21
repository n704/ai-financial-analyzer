"""Document upload, detail, and SSE progress endpoints (P2.1/P2.2).

``POST /api/v1/documents`` is the P2.2 upload endpoint: validate -> store ->
insert -> enqueue -> 202. ``GET /api/v1/documents/{id}/events`` is the P2.1 SSE
progress stream: it sends an immediate snapshot of the document's current
status (so a client that connects after processing already finished still
sees where things ended up — the ``EventBus`` has no replay, see its protocol
docstring) and then streams live updates, closing once a terminal status
(``ready``/``failed``) is reached.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.api.dependencies import get_app_state, get_current_user, get_db_session
from app.api.state import AppState
from app.db.models import Document, User
from app.db.repositories import DocumentRepository
from app.domain.validation import InvalidPdfError, NotAPdf, PdfTooLarge, PdfTooManyPages
from app.services.documents import QuotaExceeded, UploadLimits, upload_document
from app.services.jobs import document_channel

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

_TERMINAL_STATUSES = {"ready", "failed"}


class DocumentResponse(BaseModel):
    id: str
    filename: str
    status: str
    stage: str | None
    page_count: int | None


def _to_response(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        stage=document.stage,
        page_count=document.page_count,
    )


def _upload_limits(state: AppState) -> UploadLimits:
    limits = state.settings.limits
    return UploadLimits(
        max_upload_mb=limits.max_upload_mb,
        max_pages=limits.max_pages,
        default_document_quota=limits.quotas.documents,
    )


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload(
    file: UploadFile,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    state: Annotated[AppState, Depends(get_app_state)],
) -> DocumentResponse:
    data = await file.read()
    try:
        document = await upload_document(
            user=current_user,
            filename=file.filename or "upload.pdf",
            data=data,
            session=session,
            storage=state.storage,
            queue=state.infra.queue,
            limits=_upload_limits(state),
        )
    except PdfTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except (NotAPdf, PdfTooManyPages) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except InvalidPdfError as exc:  # pragma: no cover - safety net for future subclasses
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except QuotaExceeded as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return _to_response(document)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> DocumentResponse:
    document = DocumentRepository(session).get(document_id=document_id, user_id=current_user.id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return _to_response(document)


@router.get("/{document_id}/events")
async def document_events(
    document_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    state: Annotated[AppState, Depends(get_app_state)],
) -> StreamingResponse:
    document = DocumentRepository(session).get(document_id=document_id, user_id=current_user.id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")

    channel = document_channel(document_id)
    initial_snapshot = {"status": document.status, "stage": document.stage}

    async def event_stream() -> AsyncIterator[str]:
        # Subscribe *before* using the already-fetched snapshot: any event
        # published between the DB read above and this point is captured in
        # the subscriber's queue and simply delivered after the snapshot,
        # rather than lost — see EventBus.subscribe's docstring for why
        # subscribing first is what makes this race-free.
        stream = await state.infra.events.subscribe(channel)
        yield _sse_frame(initial_snapshot)
        if initial_snapshot["status"] in _TERMINAL_STATUSES:
            return
        async for event in stream:
            yield _sse_frame(event)
            if event.get("status") in _TERMINAL_STATUSES:
                return

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse_frame(event: Mapping[str, object]) -> str:
    return f"data: {json.dumps(event)}\n\n"
