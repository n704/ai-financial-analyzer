"""Redis pub/sub ``EventBus`` implementation (P1.10, scaled profile).

Kept in its own module so importing the in-process default never requires
``redis`` — only ``app/infra/factory.py`` imports this, and only when
``events.backend: redis`` is configured. Reaches subscribers across every API
replica, unlike the in-process bus.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping

from redis.asyncio import Redis


class RedisEventBus:
    """Redis-backed ``EventBus``. Events are JSON-encoded on the wire."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, channel: str, event: Mapping[str, object]) -> None:
        await self._redis.publish(channel, json.dumps(dict(event)))

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, object]]:
        # `await pubsub.subscribe(...)` registers with Redis before this
        # coroutine returns — same eager-registration guarantee as
        # `InProcessEventBus.subscribe` (see that method's comment).
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)

        async def _iterator() -> AsyncIterator[dict[str, object]]:
            try:
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    yield json.loads(data)
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()  # type: ignore[no-untyped-call]  # untyped in redis-py stubs

        return _iterator()
