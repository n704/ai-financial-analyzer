"""Watchlist persistence. Exercises the repository contract, not the SQL."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("KRONOS_PRELOAD", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import storage  # noqa: E402
from backend.app.storage.base import NotFound, StorageError, WatchlistRepository  # noqa: E402
from backend.app.storage.sqlite_repo import SQLiteWatchlistRepository  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "nested" / "watchlists.db"


@pytest.fixture
def repo(db_path):
    r = SQLiteWatchlistRepository(db_path)
    yield r
    r.close()


# ---------------------------------------------------------------- contract


def test_sqlite_repo_satisfies_the_repository_protocol(repo):
    assert isinstance(repo, WatchlistRepository)


def test_creating_the_repo_creates_missing_parent_directories(db_path, repo):
    assert db_path.exists()


# -------------------------------------------------------------------- CRUD


def test_create_list_and_get(repo):
    created = repo.create_watchlist("Tech")
    assert created.name == "Tech"
    assert created.items == []
    assert created.created_at is not None

    assert [w.name for w in repo.list_watchlists()] == ["Tech"]
    assert repo.get_watchlist(created.id).id == created.id


def test_watchlists_list_in_creation_order(repo):
    for name in ("First", "Second", "Third"):
        repo.create_watchlist(name)
    assert [w.name for w in repo.list_watchlists()] == ["First", "Second", "Third"]


def test_rename(repo):
    wl = repo.create_watchlist("Tech")
    assert repo.rename_watchlist(wl.id, "  Megacaps  ").name == "Megacaps"


def test_blank_names_are_rejected(repo):
    with pytest.raises(StorageError):
        repo.create_watchlist("   ")


def test_delete_removes_the_list(repo):
    wl = repo.create_watchlist("Tech")
    repo.delete_watchlist(wl.id)
    assert repo.list_watchlists() == []
    with pytest.raises(NotFound):
        repo.get_watchlist(wl.id)


def test_missing_watchlist_raises_not_found(repo):
    for call in (
        lambda: repo.get_watchlist(999),
        lambda: repo.rename_watchlist(999, "x"),
        lambda: repo.delete_watchlist(999),
        lambda: repo.add_symbol(999, "AAPL"),
        lambda: repo.remove_symbol(999, "AAPL"),
    ):
        with pytest.raises(NotFound):
            call()


# ----------------------------------------------------------------- symbols


def test_symbols_are_normalised_to_upper_case(repo):
    wl = repo.create_watchlist("Tech")
    out = repo.add_symbol(wl.id, "  aapl ")
    assert [i.symbol for i in out.items] == ["AAPL"]


def test_adding_the_same_symbol_twice_is_idempotent(repo):
    """The UI's star button is easy to double-click; that must not 500."""
    wl = repo.create_watchlist("Tech")
    repo.add_symbol(wl.id, "AAPL")
    out = repo.add_symbol(wl.id, "aapl")
    assert [i.symbol for i in out.items] == ["AAPL"]


def test_re_adding_with_a_note_updates_the_note(repo):
    wl = repo.create_watchlist("Tech")
    repo.add_symbol(wl.id, "AAPL")
    out = repo.add_symbol(wl.id, "AAPL", note="earnings 30 Oct")
    assert out.items[0].note == "earnings 30 Oct"


def test_empty_symbol_is_rejected(repo):
    wl = repo.create_watchlist("Tech")
    with pytest.raises(StorageError):
        repo.add_symbol(wl.id, "  ")


def test_remove_symbol(repo):
    wl = repo.create_watchlist("Tech")
    repo.add_symbol(wl.id, "AAPL")
    repo.add_symbol(wl.id, "MSFT")
    out = repo.remove_symbol(wl.id, "aapl")
    assert [i.symbol for i in out.items] == ["MSFT"]


def test_removing_an_absent_symbol_is_a_no_op(repo):
    wl = repo.create_watchlist("Tech")
    repo.add_symbol(wl.id, "AAPL")
    assert [i.symbol for i in repo.remove_symbol(wl.id, "TSLA").items] == ["AAPL"]


def test_set_note_on_an_absent_symbol_raises(repo):
    wl = repo.create_watchlist("Tech")
    with pytest.raises(StorageError):
        repo.set_note(wl.id, "AAPL", "note")


def test_deleting_a_watchlist_cascades_to_its_items(repo, db_path):
    keep = repo.create_watchlist("Keep")
    drop = repo.create_watchlist("Drop")
    repo.add_symbol(keep.id, "AAPL")
    repo.add_symbol(drop.id, "TSLA")

    repo.delete_watchlist(drop.id)

    import sqlite3

    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT watchlist_id, symbol FROM watchlist_items").fetchall()
    assert rows == [(keep.id, "AAPL")]


def test_symbols_do_not_leak_between_watchlists(repo):
    a = repo.create_watchlist("A")
    b = repo.create_watchlist("B")
    repo.add_symbol(a.id, "AAPL")
    repo.add_symbol(b.id, "MSFT")
    assert [i.symbol for i in repo.get_watchlist(a.id).items] == ["AAPL"]
    assert [i.symbol for i in repo.get_watchlist(b.id).items] == ["MSFT"]


# ------------------------------------------------------------- persistence


def test_a_second_repository_sees_the_first_ones_writes(db_path):
    """Proves this is real persistence, not an in-memory dict."""
    first = SQLiteWatchlistRepository(db_path)
    wl = first.create_watchlist("Tech")
    first.add_symbol(wl.id, "NVDA", note="watch the guidance")
    first.close()

    second = SQLiteWatchlistRepository(db_path)
    try:
        loaded = second.get_watchlist(wl.id)
        assert loaded.name == "Tech"
        assert [(i.symbol, i.note) for i in loaded.items] == [("NVDA", "watch the guidance")]
    finally:
        second.close()


def test_schema_version_is_stamped(db_path, repo):
    import sqlite3

    with sqlite3.connect(str(db_path)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1


def test_concurrent_writes_do_not_corrupt_the_database(repo):
    """FastAPI serves from a thread pool, so the repo must be thread-safe."""
    import threading

    wl = repo.create_watchlist("Tech")
    symbols = [f"SYM{i}" for i in range(40)]
    threads = [threading.Thread(target=repo.add_symbol, args=(wl.id, s)) for s in symbols]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(i.symbol for i in repo.get_watchlist(wl.id).items) == sorted(symbols)


# ---------------------------------------------------------------- factory


def test_factory_builds_a_sqlite_repo_and_caches_the_singleton(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.config, "WATCHLIST_BACKEND", "sqlite")
    monkeypatch.setattr(storage.config, "WATCHLIST_DB", str(tmp_path / "factory.db"))
    storage.reset_repository()
    try:
        repo = storage.get_repository()
        assert isinstance(repo, SQLiteWatchlistRepository)
        assert storage.get_repository() is repo
    finally:
        storage.reset_repository()


def test_factory_rejects_an_unknown_backend(monkeypatch):
    monkeypatch.setattr(storage.config, "WATCHLIST_BACKEND", "postgres")
    storage.reset_repository()
    try:
        with pytest.raises(StorageError, match="postgres"):
            storage.get_repository()
    finally:
        storage.reset_repository()
