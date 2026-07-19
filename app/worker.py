"""Worker entrypoint.

P0 boots the worker process so the container topology is real. The arq queue,
ingestion job, and stage pipeline are wired in P2.1.
"""

from __future__ import annotations

import structlog

from app.logging import configure_logging

log = structlog.get_logger()


def main() -> None:
    configure_logging()
    log.info("worker.starting", note="job queue wiring lands in P2.1")


if __name__ == "__main__":
    main()
