"""Domain objects for persisted data.

Deliberately plain dataclasses: no pydantic, no SQL, no FastAPI. This is the
contract the API layer and every repository implementation agree on, so a
future non-SQLite backend has nothing to inherit from and nothing to unlearn.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class WatchlistItem:
    symbol: str
    note: str | None = None
    added_at: datetime | None = None


@dataclass(frozen=True)
class Watchlist:
    id: int
    name: str
    created_at: datetime | None = None
    items: list[WatchlistItem] = field(default_factory=list)
