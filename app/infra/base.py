"""Infrastructure protocols (P1.10): ``Cache``, ``TaskQueue``, ``EventBus``.

Same pattern as the provider protocols in ``app/providers/base.py``: core code
depends on these interfaces, never on ``redis``/``arq`` directly. Each has an
in-memory/in-process default (single-process) and a Redis-backed implementation
(scaled, multi-process) — see ARCHITECTURE.md §3.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    """Rate-limit counters + ephemeral key/value storage."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None: ...

    async def incr(self, key: str, ttl_s: int) -> int:
        """Atomically increment ``key`` and return the new count.

        The TTL is set only the *first* time a key is created (count goes 0→1);
        subsequent increments within the window don't push the expiry back out —
        that's what makes this usable as a fixed-window rate-limit counter.
        """
        ...

    async def delete(self, key: str) -> None: ...

    async def ping(self) -> bool:
        """Cheap connectivity check for readiness probes (``GET /readyz``).
        The in-memory backend is trivially always up; the Redis backend
        actually round-trips to the server."""
        ...


@runtime_checkable
class TaskQueue(Protocol):
    """Background job dispatch (ingestion/analysis). In-process by default —
    jobs run as asyncio tasks inside the API; ``arq`` (Redis-backed) unlocks a
    separate worker process."""

    async def enqueue(self, job: str, **kwargs: object) -> str:
        """Schedule ``job`` (a registered handler name) and return a job id."""
        ...


@runtime_checkable
class EventBus(Protocol):
    """SSE progress fan-out. In-process reaches only subscribers in the same
    process; Redis pub/sub reaches subscribers across API replicas."""

    async def publish(self, channel: str, event: Mapping[str, object]) -> None: ...

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, object]]:
        """Register interest in ``channel`` and return an async iterator of
        events from that point onward (no history/replay).

        Deliberately ``async`` rather than returning a bare generator: the
        subscription must be registered *before* this coroutine returns, so a
        ``publish`` that happens-after ``await bus.subscribe(...)`` in program
        order is guaranteed to be observed. A plain generator function would
        defer registration to the first ``anext()``, opening a window where an
        event published between "subscribe" and "start iterating" is lost.
        """
        ...
