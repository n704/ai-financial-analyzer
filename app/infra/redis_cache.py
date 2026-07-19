"""Redis ``Cache`` implementation (P1.10, scaled profile).

Kept in its own module (rather than alongside ``MemoryCache`` in ``cache.py``)
so importing the in-memory default never requires the ``redis`` package —
only ``app/infra/factory.py`` imports this module, and only when
``cache.backend: redis`` is configured.
"""

from __future__ import annotations

from redis.asyncio import Redis


class RedisCache:
    """Redis-backed ``Cache``. Unlocks sharing rate-limit state (and any other
    cached value) across multiple API replicas — the in-memory backend can't."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(key)
        return None if value is None else value.decode() if isinstance(value, bytes) else value

    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        await self._redis.set(key, value, ex=ttl_s)

    async def incr(self, key: str, ttl_s: int) -> int:
        # INCR then EXPIRE-only-when-new (count == 1): the window's expiry is
        # set once, on the request that creates the key, and never pushed back
        # out by later increments — the standard fixed-window rate-limit idiom.
        new_count = int(await self._redis.incr(key))
        if new_count == 1:
            await self._redis.expire(key, ttl_s)
        return new_count

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def ping(self) -> bool:
        return bool(await self._redis.ping())
