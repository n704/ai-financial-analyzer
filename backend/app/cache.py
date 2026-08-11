"""A small thread-safe TTL cache.

Watchlist, comparison and sector views all fan out over several symbols, and
yfinance is the slowest thing in a request by an order of magnitude. Caching
by (symbol, interval, bars) for less than one bar's worth of time keeps those
views responsive without ever showing data older than the bar it belongs to.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Generic, Hashable, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Map key -> value, where entries expire `ttl` seconds after insertion.

    `clock` is injectable so tests can advance time without sleeping.
    """

    def __init__(
        self,
        ttl: float,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[Hashable, tuple[float, T]] = {}

    def get(self, key: Hashable) -> T | None:
        """Cached value, or None when absent or expired."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if self._clock() >= expires_at:
                del self._entries[key]
                return None
            return value

    def set(self, key: Hashable, value: T, ttl: float | None = None) -> None:
        """Store `value`. `ttl` overrides the cache default for this entry —
        daily bars can be held far longer than 15-minute bars."""
        with self._lock:
            if len(self._entries) >= self.max_entries and key not in self._entries:
                self._evict()
            self._entries[key] = (self._clock() + (self.ttl if ttl is None else ttl), value)

    def get_or_set(self, key: Hashable, factory: Callable[[], T], ttl: float | None = None) -> T:
        """Return the cached value, or build, store and return a fresh one.

        `factory` runs outside the lock: it is a network call, and holding the
        lock would serialise fetches for *different* symbols. The cost is that
        two simultaneous misses on the same key may both fetch, which is
        harmless — the second simply overwrites an identical entry.
        """
        hit = self.get(key)
        if hit is not None:
            return hit
        value = factory()
        self.set(key, value, ttl=ttl)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _evict(self) -> None:
        """Drop expired entries, then the nearest-to-expiry. Lock held."""
        now = self._clock()
        for key in [k for k, (exp, _) in self._entries.items() if now >= exp]:
            del self._entries[key]
        while len(self._entries) >= self.max_entries:
            oldest = min(self._entries, key=lambda k: self._entries[k][0])
            del self._entries[oldest]
