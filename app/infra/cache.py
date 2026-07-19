"""``Cache`` implementations (P1.10): in-memory default + Redis (scaled).

The in-memory backend is correct only single-process — its dict lives in one
process's memory (ARCHITECTURE.md §3). It's still async-safe via a lock so
concurrent request handlers on the same event loop can't race the same counter.
"""

from __future__ import annotations

import asyncio
import time


class MemoryCache:
    """Per-process TTL dict. Default backend; implies single-process."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float | None]] = {}
        self._counters: dict[str, tuple[int, float | None]] = {}
        self._lock = asyncio.Lock()

    def _expired(self, expires_at: float | None) -> bool:
        return expires_at is not None and time.monotonic() >= expires_at

    async def get(self, key: str) -> str | None:
        async with self._lock:
            entry = self._values.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if self._expired(expires_at):
                del self._values[key]
                return None
            return value

    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        expires_at = time.monotonic() + ttl_s if ttl_s is not None else None
        async with self._lock:
            self._values[key] = (value, expires_at)

    async def incr(self, key: str, ttl_s: int) -> int:
        async with self._lock:
            entry = self._counters.get(key)
            if entry is not None and self._expired(entry[1]):
                entry = None
            if entry is None:
                new_count = 1
                self._counters[key] = (new_count, time.monotonic() + ttl_s)
            else:
                new_count = entry[0] + 1
                self._counters[key] = (new_count, entry[1])  # keep original expiry
            return new_count

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._values.pop(key, None)
            self._counters.pop(key, None)

    async def ping(self) -> bool:
        return True
