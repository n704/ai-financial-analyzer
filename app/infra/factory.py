"""Config → concrete infra backends (P1.10) — same pattern as
``app/providers/factory.py``: core code asks for ``Cache``/``TaskQueue``/
``EventBus`` and this is the only place a config string maps to a concrete
class. Vendor imports (``redis``, ``arq``) are deferred so the in-memory/
in-process defaults never require those packages installed.

Async throughout: building the ``arq`` backend awaits a Redis connection pool,
so rather than split into a sync path (memory/inprocess) and an async path
(redis/arq), every ``build_*`` function here is a coroutine. Call these from
the FastAPI lifespan (an async context) at startup.

``Settings`` already rejects incoherent combinations at load time (a Redis
backend with no URL, or ``arq`` paired with an in-memory cache/events) — see
``app/config/models.py``'s ``_check_backend_coherence`` — so this module can
assume the config it receives is internally consistent.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.infra.base import Cache, EventBus, TaskQueue
from app.infra.cache import MemoryCache
from app.infra.queue import InProcessQueue


@dataclass(frozen=True, slots=True)
class InfraBundle:
    cache: Cache
    queue: TaskQueue
    events: EventBus


async def build_cache(settings: Settings) -> Cache:
    if settings.cache.backend == "memory":
        return MemoryCache()

    from redis.asyncio import Redis

    from app.infra.redis_cache import RedisCache

    assert settings.cache.url is not None  # enforced by Settings validation
    return RedisCache(Redis.from_url(settings.cache.url))


async def build_queue(settings: Settings) -> TaskQueue:
    if settings.queue.backend == "inprocess":
        return InProcessQueue()

    from arq.connections import RedisSettings, create_pool

    from app.infra.arq_queue import ArqQueue

    assert settings.queue.url is not None  # enforced by Settings validation
    pool = await create_pool(RedisSettings.from_dsn(settings.queue.url))
    return ArqQueue(pool)


async def build_events(settings: Settings) -> EventBus:
    if settings.events.backend == "inprocess":
        from app.infra.events import InProcessEventBus

        return InProcessEventBus()

    from redis.asyncio import Redis

    from app.infra.redis_events import RedisEventBus

    assert settings.events.url is not None  # enforced by Settings validation
    return RedisEventBus(Redis.from_url(settings.events.url))


async def build_infra(settings: Settings) -> InfraBundle:
    return InfraBundle(
        cache=await build_cache(settings),
        queue=await build_queue(settings),
        events=await build_events(settings),
    )
