"""Worker entrypoint (P2.1) — the real arq worker for the scaled profile.

Meaningful only when ``queue.backend: arq`` (``config/scaled.yaml``); the
default single-process profile runs the same job body inline via
``InProcessQueue`` inside the API process instead (``app/main.py``'s
lifespan registers it there). Job logic lives in ``app/services/jobs.py`` and
is identical either way — this module is only the arq-specific dispatch shim
plus connection bootstrap.
"""

from __future__ import annotations

from typing import Any, ClassVar

import structlog
from arq.connections import RedisSettings
from arq.worker import Function, func, run_worker

from app.config import ConfigError, load_settings
from app.db.base import build_engine, build_session_factory
from app.infra.factory import build_events
from app.logging import configure_logging
from app.services.jobs import INGEST_DOCUMENT_JOB, JobContext, run_ingest_document

log = structlog.get_logger()


def _require_arq_queue_url() -> str:
    """Fail fast if this process is started against a non-arq profile —
    running the worker only makes sense when the queue backend is arq."""
    settings = load_settings()
    if settings.queue.backend != "arq" or not settings.queue.url:
        raise ConfigError(
            f"app.worker requires queue.backend='arq' with a queue.url set "
            f"(configured: backend={settings.queue.backend!r}); the "
            f"single-process profile runs ingestion jobs inline in the API "
            f"process instead (see app/main.py)"
        )
    return settings.queue.url


_queue_url = _require_arq_queue_url()


async def _on_startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    settings = load_settings()
    engine = build_engine(settings.database.url)
    session_factory = build_session_factory(engine)
    events = await build_events(settings)
    ctx["job_ctx"] = JobContext(session_factory=session_factory, events=events)
    log.info("worker.startup", queue_backend=settings.queue.backend)


async def _ingest_document(ctx: dict[str, Any], *, document_id: str, user_id: str) -> None:
    await run_ingest_document(ctx["job_ctx"], document_id=document_id, user_id=user_id)


class WorkerSettings:
    """Read by arq's CLI (``arq app.worker.WorkerSettings``) and by
    :func:`main` below — same job registered under the same name
    (``INGEST_DOCUMENT_JOB``) that ``app/main.py`` uses for the in-process
    queue, so the upload endpoint's ``queue.enqueue(...)`` call doesn't need
    to know which backend is running it.
    """

    # `WorkerSettings` is never instantiated — arq's CLI reads these as plain
    # class attributes (see `arq.worker.get_kwargs`) — but ruff flags a bare
    # list default as mutable-shared-state regardless, so it's spelled as a
    # ClassVar to make that "namespace, not instances" intent explicit.
    functions: ClassVar[list[Function]] = [func(_ingest_document, name=INGEST_DOCUMENT_JOB)]
    on_startup = _on_startup
    redis_settings = RedisSettings.from_dsn(_queue_url)


def main() -> None:
    """``python -m app.worker`` — run the arq worker loop in-process (an
    alternative to the ``arq`` CLI, used by ``docker/entrypoint.sh``)."""
    # arq's `WorkerSettingsType` is a Protocol (`WorkerSettingsBase` in
    # arq/typing.py) checked structurally against `type[WorkerSettings]`;
    # mypy can't verify that shape for a plain settings class the way arq's
    # own runtime `get_kwargs()` (which just reads `__dict__`) does.
    run_worker(WorkerSettings)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
