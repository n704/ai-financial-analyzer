"""Generic exponential-backoff-with-jitter retry helper for provider adapters.

Vendor-neutral on purpose: it knows nothing about any specific SDK's exceptions.
Each adapter supplies a small classifier (``is_retryable``) that maps its own
vendor exception to a retry-after hint. This is the one piece of backoff logic
shared across adapters so each one doesn't reinvent jittered exponential delay.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def with_backoff(  # noqa: UP047 - TypeVar kept consistent with TModel in providers/base.py
    fn: Callable[[], T],
    *,
    is_retryable: Callable[[Exception], float | None],
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn()``, retrying on transient failures with exponential backoff.

    ``is_retryable(exc)`` returns:
      - ``None`` — not retryable; the exception propagates immediately.
      - ``0.0``  — retryable, no explicit hint; delay is computed from ``attempt``.
      - a positive float — retryable with an explicit retry-after (seconds),
        used as-is (e.g. from a provider's ``Retry-After`` header).
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            hint = is_retryable(exc)
            if hint is None or attempt >= max_retries:
                raise
            delay = hint if hint > 0 else min(max_delay, base_delay * (2**attempt))
            delay += random.uniform(0, delay * 0.1)
            sleep(delay)
            attempt += 1
