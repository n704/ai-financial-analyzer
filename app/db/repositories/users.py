"""User repository — the only code that reads/writes the ``users`` table.

Email lookups normalize to lowercase before hitting the DB (the portable stand-
in for the citext behavior described in ``app/db/models.py``'s module
docstring). Callers pass raw user input; this repository normalizes once.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.base import new_uuid, utcnow
from app.db.models import User
from app.db.repositories.base import ScopedRepository


class UserAlreadyExists(Exception):
    """Raised on registration when the (normalized) email is already taken."""


class UserRepository(ScopedRepository):
    def create(self, *, email: str, password_hash: str) -> User:
        normalized = email.strip().lower()
        if self.get_by_email(normalized) is not None:
            raise UserAlreadyExists(normalized)
        user = User(
            id=new_uuid(), email=normalized, password_hash=password_hash, created_at=utcnow()
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        return self.session.scalar(select(User).where(User.email == normalized))

    def get_by_id(self, user_id: str) -> User | None:
        """Not a cross-tenant risk despite the bare-ID lookup: every call site
        passes the *authenticated* principal's own id (from the verified JWT),
        never an id supplied by the request body/path."""
        return self.session.get(User, user_id)

    def delete(self, user_id: str) -> None:
        """Delete the user row; FK cascades remove refresh tokens (and, once
        those tables are populated in P2-P4, documents/analyses/conversations).
        Object-storage and vector-store cleanup are separate idempotent jobs —
        see ARCHITECTURE.md §5 "Data lifecycle" — added alongside those features."""
        user = self.session.get(User, user_id)
        if user is not None:
            self.session.delete(user)
            self.session.flush()
