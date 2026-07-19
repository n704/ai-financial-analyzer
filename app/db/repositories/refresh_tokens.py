"""Refresh-token repository — hashed, rotating, revocable (SPEC.md §3.1).

Tokens are never stored in plaintext (``token_hash`` only, computed by the auth
service). Rotation revokes the presented token and inserts a new one in the same
transaction, so a stolen-then-replayed refresh token fails the very next use.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.db.base import new_uuid, utcnow
from app.db.models import RefreshToken
from app.db.repositories.base import ScopedRepository


class RefreshTokenRepository(ScopedRepository):
    def create(self, *, user_id: str, token_hash: str, expires_at: datetime) -> RefreshToken:
        token = RefreshToken(
            id=new_uuid(),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            created_at=utcnow(),
        )
        self.session.add(token)
        self.session.flush()
        return token

    def get_valid(self, *, user_id: str, token_hash: str) -> RefreshToken | None:
        """Usable only if it belongs to ``user_id``, is unexpired, and unrevoked
        — every check server-side, none inferred from the token contents."""
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > utcnow(),
        )
        return self.session.scalar(stmt)

    def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Look up by hash alone, with no separately-supplied ``user_id``.

        Not a violation of the "no bare-ID lookup" convention: the presented
        refresh token *is* the credential here (a high-entropy secret only its
        holder possesses), exactly like a JWT's signature — there is no
        attacker-controlled id to spoof. Callers must still check
        ``revoked_at``/``expires_at`` (``AuthService.refresh`` does).
        """
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return self.session.scalar(stmt)

    def revoke(self, *, user_id: str, token_hash: str) -> None:
        token = self.session.scalar(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.token_hash == token_hash
            )
        )
        if token is not None and token.revoked_at is None:
            token.revoked_at = utcnow()
            self.session.flush()

    def revoke_all_for_user(self, user_id: str) -> None:
        """Used on logout-everywhere and account deletion."""
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
        for token in self.session.scalars(stmt):
            token.revoked_at = utcnow()
        self.session.flush()
