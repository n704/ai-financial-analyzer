"""P1.10: in-memory Cache/TaskQueue/EventBus — the default single-process
backends. Redis-backed equivalents are exercised in CI's testcontainers
integration job (no live Redis in this environment)."""

from __future__ import annotations

import asyncio

import pytest

from app.infra.cache import MemoryCache
from app.infra.events import InProcessEventBus
from app.infra.queue import InProcessQueue


async def test_cache_get_set_roundtrip() -> None:
    cache = MemoryCache()
    assert await cache.get("k") is None
    await cache.set("k", "v")
    assert await cache.get("k") == "v"


async def test_cache_set_ttl_expires() -> None:
    cache = MemoryCache()
    await cache.set("k", "v", ttl_s=0)
    await asyncio.sleep(0.01)
    assert await cache.get("k") is None


async def test_cache_delete() -> None:
    cache = MemoryCache()
    await cache.set("k", "v")
    await cache.delete("k")
    assert await cache.get("k") is None


async def test_cache_incr_counts_up() -> None:
    cache = MemoryCache()
    assert await cache.incr("counter", ttl_s=60) == 1
    assert await cache.incr("counter", ttl_s=60) == 2
    assert await cache.incr("counter", ttl_s=60) == 3


async def test_cache_incr_is_isolated_per_key() -> None:
    cache = MemoryCache()
    await cache.incr("a", ttl_s=60)
    assert await cache.incr("b", ttl_s=60) == 1


async def test_cache_incr_resets_after_ttl_expiry() -> None:
    cache = MemoryCache()
    await cache.incr("k", ttl_s=0)
    await asyncio.sleep(0.01)
    assert await cache.incr("k", ttl_s=60) == 1


async def test_cache_incr_concurrent_is_atomic() -> None:
    cache = MemoryCache()
    await asyncio.gather(*[cache.incr("hot", ttl_s=60) for _ in range(50)])
    assert await cache.get("hot") is None  # separate counter/value namespaces
    # There's no direct counter getter, so verify via one more increment.
    assert await cache.incr("hot", ttl_s=60) == 51


async def test_queue_enqueue_runs_registered_handler() -> None:
    queue = InProcessQueue()
    seen: list[str] = []

    async def handler(*, doc_id: str) -> None:
        seen.append(doc_id)

    queue.register("ingest", handler)
    await queue.enqueue("ingest", doc_id="abc")
    await asyncio.sleep(0.01)  # let the scheduled task run
    assert seen == ["abc"]


async def test_queue_enqueue_unknown_job_raises() -> None:
    queue = InProcessQueue()
    with pytest.raises(KeyError):
        await queue.enqueue("nope")


async def test_queue_handler_exception_does_not_crash_caller() -> None:
    queue = InProcessQueue()

    async def failing_handler() -> None:
        raise RuntimeError("boom")

    queue.register("fails", failing_handler)
    job_id = await queue.enqueue("fails")  # must not raise synchronously
    assert job_id
    await asyncio.sleep(0.01)  # the background task's failure is swallowed+logged


async def test_events_publish_subscribe_single_subscriber() -> None:
    bus = InProcessEventBus()
    stream = await bus.subscribe("doc-1")

    await bus.publish("doc-1", {"stage": "queued"})
    event = await anext(stream)
    assert event == {"stage": "queued"}


async def test_events_multiple_subscribers_all_receive() -> None:
    bus = InProcessEventBus()
    stream_a = await bus.subscribe("doc-1")
    stream_b = await bus.subscribe("doc-1")

    await bus.publish("doc-1", {"stage": "processing"})

    assert await anext(stream_a) == {"stage": "processing"}
    assert await anext(stream_b) == {"stage": "processing"}


async def test_events_scoped_by_channel() -> None:
    bus = InProcessEventBus()
    stream = await bus.subscribe("doc-1")

    await bus.publish("doc-2", {"stage": "queued"})  # different channel
    await bus.publish("doc-1", {"stage": "ready"})

    event = await anext(stream)
    assert event == {"stage": "ready"}
