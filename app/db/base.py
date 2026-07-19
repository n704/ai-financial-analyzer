"""SQLAlchemy engine/session plumbing + the declarative base (P1.8).

Kept intentionally small: this module and ``models.py`` are the only places
outside ``app/providers``/``app/infra`` that touch a vendor SQL driver — and
even then, only indirectly through the SQLAlchemy URL scheme. No dialect-
specific types leak into the model definitions, so the same models produce
working DDL on SQLite (default) and Postgres (scaled profile).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in ``models.py``."""


def new_uuid() -> str:
    """String UUID primary key — portable across SQLite (no native UUID type)
    and Postgres; call sites don't need a dialect-specific column type."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """A naive UTC timestamp.

    SQLite doesn't preserve ``tzinfo`` across a round trip — even a column
    declared ``DateTime(timezone=True)`` comes back naive there — so every
    datetime this app stores is naive-but-implicitly-UTC, on both SQLite and
    Postgres. Comparing a freshly-made aware datetime against one just read
    back from the DB would otherwise raise ``TypeError``; using this
    everywhere a "now" is needed for a persisted column avoids that mismatch.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def build_engine(url: str, *, echo: bool = False) -> Engine:
    """Create the SQLAlchemy engine for ``url``.

    SQLite needs ``check_same_thread=False``: FastAPI may serve a request on a
    different thread than the one that opened the connection. Fine at
    single-process scale; the scaled profile uses Postgres instead.
    """
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, echo=echo, connect_args=connect_args)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on success, rollback on error — the unit-of-work wrapper services
    use around one or more repository calls."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
