"""SQLite implementation of `WatchlistRepository`.

This is the only module in the project that contains SQL. Keep it that way: the
point of the Protocol in `base.py` is that swapping databases touches one file.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .base import NotFound, StorageError, normalize_name, normalize_symbol
from .models import Watchlist, WatchlistItem

# Bump when the schema changes and add a migration step in `_migrate`.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_items (
    watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    symbol       TEXT NOT NULL,
    note         TEXT,
    added_at     TEXT NOT NULL,
    PRIMARY KEY (watchlist_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_items_watchlist ON watchlist_items(watchlist_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class SQLiteWatchlistRepository:
    """Thread-safe repository backed by a single SQLite file.

    One connection shared across threads with `check_same_thread=False` and a
    lock around every operation — the same approach `KronosEngine` takes for
    inference. Traffic here is a handful of tiny queries per page load, so a
    connection pool would be complexity without benefit.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.parent and str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            # WAL keeps a reader (the UI polling quotes) from blocking a writer.
            if str(self.path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(_SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """Apply schema upgrades. Called with the lock held."""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        # No migrations yet — v1 is the initial schema, created above.
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------- internals

    def _load(self, watchlist_id: int) -> Watchlist:
        """Read one watchlist with its items. Called with the lock held."""
        row = self._conn.execute(
            "SELECT id, name, created_at FROM watchlists WHERE id = ?", (watchlist_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"Watchlist {watchlist_id} does not exist.")
        items = self._conn.execute(
            "SELECT symbol, note, added_at FROM watchlist_items "
            "WHERE watchlist_id = ? ORDER BY added_at, symbol",
            (watchlist_id,),
        ).fetchall()
        return Watchlist(
            id=row["id"],
            name=row["name"],
            created_at=_parse_ts(row["created_at"]),
            items=[
                WatchlistItem(symbol=i["symbol"], note=i["note"], added_at=_parse_ts(i["added_at"]))
                for i in items
            ],
        )

    def _require(self, watchlist_id: int) -> None:
        """Raise `NotFound` unless the watchlist exists. Lock held."""
        if self._conn.execute(
            "SELECT 1 FROM watchlists WHERE id = ?", (watchlist_id,)
        ).fetchone() is None:
            raise NotFound(f"Watchlist {watchlist_id} does not exist.")

    # ---------------------------------------------------------------- public

    def list_watchlists(self) -> list[Watchlist]:
        with self._lock:
            ids = [
                r["id"]
                for r in self._conn.execute("SELECT id FROM watchlists ORDER BY id").fetchall()
            ]
            return [self._load(i) for i in ids]

    def get_watchlist(self, watchlist_id: int) -> Watchlist:
        with self._lock:
            return self._load(watchlist_id)

    def create_watchlist(self, name: str) -> Watchlist:
        name = normalize_name(name)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO watchlists (name, created_at) VALUES (?, ?)", (name, _now())
            )
            self._conn.commit()
            return self._load(int(cur.lastrowid))

    def rename_watchlist(self, watchlist_id: int, name: str) -> Watchlist:
        name = normalize_name(name)
        with self._lock:
            self._require(watchlist_id)
            self._conn.execute("UPDATE watchlists SET name = ? WHERE id = ?", (name, watchlist_id))
            self._conn.commit()
            return self._load(watchlist_id)

    def delete_watchlist(self, watchlist_id: int) -> None:
        with self._lock:
            self._require(watchlist_id)
            # Explicit item delete as well: ON DELETE CASCADE only fires when
            # `PRAGMA foreign_keys` is on, and that is per-connection state.
            self._conn.execute("DELETE FROM watchlist_items WHERE watchlist_id = ?", (watchlist_id,))
            self._conn.execute("DELETE FROM watchlists WHERE id = ?", (watchlist_id,))
            self._conn.commit()

    def add_symbol(self, watchlist_id: int, symbol: str, note: str | None = None) -> Watchlist:
        symbol = normalize_symbol(symbol)
        with self._lock:
            self._require(watchlist_id)
            # Idempotent: re-adding keeps the original `added_at` and ordering.
            self._conn.execute(
                "INSERT OR IGNORE INTO watchlist_items (watchlist_id, symbol, note, added_at) "
                "VALUES (?, ?, ?, ?)",
                (watchlist_id, symbol, note, _now()),
            )
            if note is not None:
                self._conn.execute(
                    "UPDATE watchlist_items SET note = ? WHERE watchlist_id = ? AND symbol = ?",
                    (note, watchlist_id, symbol),
                )
            self._conn.commit()
            return self._load(watchlist_id)

    def remove_symbol(self, watchlist_id: int, symbol: str) -> Watchlist:
        symbol = normalize_symbol(symbol)
        with self._lock:
            self._require(watchlist_id)
            self._conn.execute(
                "DELETE FROM watchlist_items WHERE watchlist_id = ? AND symbol = ?",
                (watchlist_id, symbol),
            )
            self._conn.commit()
            return self._load(watchlist_id)

    def set_note(self, watchlist_id: int, symbol: str, note: str | None) -> Watchlist:
        symbol = normalize_symbol(symbol)
        with self._lock:
            self._require(watchlist_id)
            cur = self._conn.execute(
                "UPDATE watchlist_items SET note = ? WHERE watchlist_id = ? AND symbol = ?",
                (note, watchlist_id, symbol),
            )
            if cur.rowcount == 0:
                raise StorageError(f"{symbol} is not in watchlist {watchlist_id}.")
            self._conn.commit()
            return self._load(watchlist_id)
