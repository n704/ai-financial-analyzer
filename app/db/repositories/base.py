"""Repository base.

Deliberately thin: it exists to give every concrete repository the same
constructor shape, not to offer a generic ``get(id)`` — that shape is exactly
the footgun (SPEC.md §3.1, "object IDs alone never grant access") the per-
resource repositories are designed to make hard to write by accident.
"""

from __future__ import annotations

from sqlalchemy.orm import Session


class ScopedRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
