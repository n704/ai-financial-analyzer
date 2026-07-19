"""In-process ``TaskQueue`` implementation (P1.10) — the default backend.

No separate worker: a job runs as an asyncio task on the API process's own
event loop. Handlers are registered by name (services register their ingestion/
analysis jobs at startup); ``enqueue`` schedules the coroutine immediately.
This shares the event loop with request handling — fine at low concurrency, and
precisely the signal to switch to the ``arq`` backend (``app/infra/arq_queue.py``)
as load grows (ARCHITECTURE.md §2).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import structlog

log = structlog.get_logger()


class InProcessQueue:
    """Asyncio-task queue. Jobs die with the process — there's no durability
    until the ``arq`` (Redis-backed) backend is selected."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Awaitable[None]]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def register(self, job: str, handler: Callable[..., Awaitable[None]]) -> None:
        """Register the coroutine that runs when ``job`` is enqueued. Services
        call this once at startup for each job type they own."""
        self._handlers[job] = handler

    async def enqueue(self, job: str, **kwargs: object) -> str:
        handler = self._handlers.get(job)
        if handler is None:
            raise KeyError(
                f"no handler registered for job {job!r} (known jobs: {sorted(self._handlers)})"
            )
        job_id = str(uuid.uuid4())
        coro = self._run(job=job, job_id=job_id, handler=handler, kwargs=kwargs)
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job_id

    async def _run(
        self,
        *,
        job: str,
        job_id: str,
        handler: Callable[..., Awaitable[None]],
        kwargs: dict[str, object],
    ) -> None:
        try:
            await handler(**kwargs)
        except Exception:
            # A background task's exception is otherwise silently swallowed
            # (asyncio only logs "exception never retrieved" at GC time).
            # Real per-stage retry/dead-letter handling lands in P2.8; this is
            # the minimal safety net so failures are at least visible today.
            log.exception("inprocess_queue.job_failed", job=job, job_id=job_id)
