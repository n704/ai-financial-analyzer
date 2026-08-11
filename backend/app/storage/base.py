"""The persistence contract, independent of any database.

Everything above this layer talks to `WatchlistRepository`. Swapping SQLite for
Postgres (or anything else) means writing one new module that satisfies this
Protocol and pointing the factory in `__init__` at it — no caller changes.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Watchlist


class StorageError(RuntimeError):
    """Persistence failed for a reason the caller can act on."""


class NotFound(StorageError):
    """The requested watchlist does not exist."""


def normalize_symbol(symbol: str) -> str:
    """Canonical ticker form. Yahoo symbols are upper-case ('brk-b' -> 'BRK-B')."""
    out = symbol.strip().upper()
    if not out:
        raise StorageError("Symbol is required.")
    return out


def normalize_name(name: str) -> str:
    out = name.strip()
    if not out:
        raise StorageError("Watchlist name is required.")
    return out


@runtime_checkable
class WatchlistRepository(Protocol):
    """CRUD over watchlists and their symbols.

    Implementations must:
      * normalise symbols with `normalize_symbol` before storing;
      * treat `add_symbol` for an existing symbol as a no-op (idempotent), not
        an error, so a double-click on the UI's star button is harmless;
      * raise `NotFound` when a watchlist id does not exist;
      * be safe to call from multiple threads — FastAPI serves requests from a
        thread pool.
    """

    def list_watchlists(self) -> list[Watchlist]:
        """All watchlists with their items, oldest first."""
        ...

    def get_watchlist(self, watchlist_id: int) -> Watchlist:
        """One watchlist with its items. Raises `NotFound`."""
        ...

    def create_watchlist(self, name: str) -> Watchlist:
        ...

    def rename_watchlist(self, watchlist_id: int, name: str) -> Watchlist:
        ...

    def delete_watchlist(self, watchlist_id: int) -> None:
        """Delete the list and its items. Raises `NotFound`."""
        ...

    def add_symbol(self, watchlist_id: int, symbol: str, note: str | None = None) -> Watchlist:
        ...

    def remove_symbol(self, watchlist_id: int, symbol: str) -> Watchlist:
        ...

    def set_note(self, watchlist_id: int, symbol: str, note: str | None) -> Watchlist:
        ...
