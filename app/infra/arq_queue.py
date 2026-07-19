"""``arq`` (Redis-backed) ``TaskQueue`` implementation (P1.10, scaled profile).

Kept in its own module so importing the in-process default never requires
``arq``/``redis`` — only ``app/infra/factory.py`` imports this, and only when
``queue.backend: arq`` is configured. Jobs enqueued here are picked up by the
separate ``app.worker`` process (wired in P2.1); this module only needs to get
a job onto the queue and hand back its id.
"""

from __future__ import annotations

from arq.connections import ArqRedis


class ArqQueue:
    """Redis-backed ``TaskQueue``. Durable — jobs survive an API restart and are
    processed by a separate worker, unlocking horizontal scaling of ingestion."""

    def __init__(self, redis: ArqRedis) -> None:
        self._redis = redis

    async def enqueue(self, job: str, **kwargs: object) -> str:
        # `enqueue_job`'s stub types its `_job_id`/`_defer_until`/etc. keyword-only
        # params individually; our `TaskQueue.enqueue(**kwargs: object)` contract
        # is deliberately generic job-payload data, so the splat can't be checked
        # against those specific reserved-name signatures statically.
        job_handle = await self._redis.enqueue_job(job, **kwargs)  # type: ignore[arg-type]
        if job_handle is None:
            # arq returns None when a job with the same `_job_id` is already
            # queued/running (dedup) — surface that rather than a fake id.
            raise RuntimeError(f"job {job!r} was not enqueued (duplicate job id?)")
        return job_handle.job_id
