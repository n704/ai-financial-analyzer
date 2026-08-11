"""Persistence for the app, behind a backend-agnostic repository interface.

Callers do `from .storage import get_repository` and never import a concrete
implementation. Adding a Postgres backend later means one new module plus one
branch in `_build`.
"""
from __future__ import annotations

import threading

from .. import config
from .base import NotFound, StorageError, WatchlistRepository, normalize_symbol
from .models import Watchlist, WatchlistItem

__all__ = [
    "NotFound",
    "StorageError",
    "Watchlist",
    "WatchlistItem",
    "WatchlistRepository",
    "get_repository",
    "normalize_symbol",
    "reset_repository",
]

_repo: WatchlistRepository | None = None
_repo_lock = threading.Lock()


def _build() -> WatchlistRepository:
    backend = config.WATCHLIST_BACKEND.lower()
    if backend == "sqlite":
        from .sqlite_repo import SQLiteWatchlistRepository

        return SQLiteWatchlistRepository(config.WATCHLIST_DB)
    raise StorageError(
        f"Unknown WATCHLIST_BACKEND '{backend}'. Supported backends: sqlite."
    )


def get_repository() -> WatchlistRepository:
    """Process-wide repository singleton, built on first use."""
    global _repo
    if _repo is None:
        with _repo_lock:
            if _repo is None:
                _repo = _build()
    return _repo


def reset_repository() -> None:
    """Drop the singleton so the next call re-reads config. For tests."""
    global _repo
    with _repo_lock:
        close = getattr(_repo, "close", None)
        if close is not None:
            close()
        _repo = None
