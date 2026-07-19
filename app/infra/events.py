"""In-process ``EventBus`` implementation (P1.10) — the default SSE progress bus.

Fan-out only reaches subscribers living in the same process (ARCHITECTURE.md
§3) — fine for single-process mode where the API that enqueues an ingestion job
is the same process that runs it and serves the SSE stream. Redis pub/sub
(``app/infra/redis_events.py``) is required once there's more than one API
replica.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Mapping


class InProcessEventBus:
    """Per-process asyncio broadcast: each subscriber gets its own queue fed by
    every ``publish`` call on that channel."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, object]]]] = defaultdict(set)

    async def publish(self, channel: str, event: Mapping[str, object]) -> None:
        for queue in list(self._subscribers.get(channel, ())):
            queue.put_nowait(dict(event))

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, object]]:
        # Registration happens here, synchronously within this coroutine —
        # before it returns — so a `publish` issued right after `await
        # subscribe(...)` can never race past an unregistered queue. See the
        # protocol docstring in `app/infra/base.py` for why this matters.
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._subscribers[channel].add(queue)

        async def _iterator() -> AsyncIterator[dict[str, object]]:
            try:
                while True:
                    yield await queue.get()
            finally:
                self._subscribers[channel].discard(queue)

        return _iterator()
