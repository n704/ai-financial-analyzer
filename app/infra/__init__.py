"""Infrastructure backends behind interfaces: Cache, TaskQueue, EventBus (P1.10).

Default backends are in-memory / in-process (single-process mode); Redis
backends unlock multiple API replicas + a separate worker. Selected by config
via ``build_infra``; only this package imports ``redis`` / ``arq``.
"""

from __future__ import annotations

from app.infra.base import Cache, EventBus, TaskQueue
from app.infra.cache import MemoryCache
from app.infra.factory import InfraBundle, build_cache, build_events, build_infra, build_queue
from app.infra.queue import InProcessQueue

__all__ = [
    "Cache",
    "EventBus",
    "InProcessQueue",
    "InfraBundle",
    "MemoryCache",
    "TaskQueue",
    "build_cache",
    "build_events",
    "build_infra",
    "build_queue",
]
