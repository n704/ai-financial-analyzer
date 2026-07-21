"""User-scoped repositories over the ORM models in ``app/db/models.py``.

Convention (ARCHITECTURE.md §6, "Authentication & authorization"): every method
that reads or writes a user-owned row takes and filters on ``user_id`` — there is
no method shaped like ``get(id)`` that skips the ownership check. Services call
these, never the ORM session directly.
"""

from __future__ import annotations

from app.db.repositories.documents import DocumentRepository
from app.db.repositories.index_meta import IndexMetaRepository
from app.db.repositories.refresh_tokens import RefreshTokenRepository
from app.db.repositories.users import UserAlreadyExists, UserRepository

__all__ = [
    "DocumentRepository",
    "IndexMetaRepository",
    "RefreshTokenRepository",
    "UserAlreadyExists",
    "UserRepository",
]
