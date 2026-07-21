"""Background job definitions (P2.1), shared by both dispatch paths:

- the in-process queue, registered directly inside the API process
  (``app/main.py``'s lifespan) when ``queue.backend: inprocess`` (default);
- the arq worker (``app/worker.py``), when ``queue.backend: arq`` (scaled).

One job body (:func:`run_ingest_document`), two thin call shims — each queue
backend's own module adapts its calling convention (arq passes a ``ctx`` dict
positionally; the in-process queue calls with keyword args only) to this
shared function, so the actual job logic is never duplicated or backend-aware.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app.db.base import session_scope
from app.db.repositories import DocumentRepository
from app.infra.base import EventBus

INGEST_DOCUMENT_JOB = "ingest_document"


def document_channel(document_id: str) -> str:
    """The ``EventBus`` channel a document's ingestion progress is published
    to and streamed from (``GET /api/v1/documents/{id}/events``)."""
    return f"document:{document_id}"


@dataclass(slots=True)
class JobContext:
    """Everything a job handler needs, independent of which queue backend
    invoked it — built once at process startup (API or worker) from config."""

    session_factory: sessionmaker[Session]
    events: EventBus


async def run_ingest_document(job_ctx: JobContext, *, document_id: str, user_id: str) -> None:
    """Placeholder ingestion job (P2.1/P2.2).

    Proves the enqueue -> worker -> progress -> status loop end-to-end
    (PLAN.md P2.1 "done when": an enqueued job runs and streams progress to
    the browser). The real multi-stage pipeline — metadata detection (P2.5),
    chunking + embedding (P2.6), metric extraction + insights (P2.7) —
    replaces this body in a later phase without changing the job name or this
    function's signature, so neither the upload endpoint (P2.2) nor the
    worker wiring (P2.1) need to change again when it lands.
    """
    channel = document_channel(document_id)

    await job_ctx.events.publish(channel, {"status": "processing", "stage": "queued_pipeline"})
    with session_scope(job_ctx.session_factory) as session:
        DocumentRepository(session).update_status(
            document_id=document_id, user_id=user_id, status="processing", stage="queued_pipeline"
        )

    await job_ctx.events.publish(channel, {"status": "ready", "stage": None})
    with session_scope(job_ctx.session_factory) as session:
        DocumentRepository(session).update_status(
            document_id=document_id, user_id=user_id, status="ready", stage=None
        )
