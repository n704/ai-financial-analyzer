"""SQLAlchemy models, repositories, and Alembic migrations (P1.8).

Portable across SQLite (default) and Postgres (scaled profile) — see the module
docstring on ``app/db/models.py`` for the specific portability decisions.
"""

from __future__ import annotations

from app.db.base import Base, build_engine, build_session_factory, session_scope
from app.db.models import (
    Analysis,
    Chunk,
    Conversation,
    Document,
    IndexMeta,
    Message,
    RefreshToken,
    Usage,
    User,
)

__all__ = [
    "Analysis",
    "Base",
    "Chunk",
    "Conversation",
    "Document",
    "IndexMeta",
    "Message",
    "RefreshToken",
    "Usage",
    "User",
    "build_engine",
    "build_session_factory",
    "session_scope",
]
