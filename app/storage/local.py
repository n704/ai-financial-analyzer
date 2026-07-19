"""Local-disk object storage adapter (P1.11) — default backend.

Objects live under a configured root directory, keyed by a relative path
(``{user_id}/{document_id}.pdf``). Signed URLs are self-issued HMAC tokens
(``app/storage/signing.py``) rather than anything served by a real object
store — verification happens wherever the API mounts the file-serving route
(``verify_signed_token``, wired to an endpoint alongside document viewing).
"""

from __future__ import annotations

from pathlib import Path

from app.storage.base import ObjectNotFound
from app.storage.signing import sign, verify


class LocalObjectStorage:
    """Filesystem implementation of :class:`~app.storage.base.ObjectStorage`."""

    def __init__(self, *, root: str, signing_secret: str, base_url: str = "/files") -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._signing_secret = signing_secret.encode()
        self._base_url = base_url.rstrip("/")

    def _resolve(self, key: str) -> Path:
        """Map ``key`` to a path under the storage root, rejecting anything
        (``../``, absolute paths) that would escape it."""
        path = (self._root / key).resolve()
        if path != self._root and self._root not in path.parents:
            raise ValueError(f"object key escapes storage root: {key!r}")
        return path

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        path.unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def signed_url(self, key: str, *, ttl_s: int = 300) -> str:
        token = sign(key=key, ttl_s=ttl_s, secret=self._signing_secret)
        return f"{self._base_url}/{token}"

    def verify_signed_token(self, token: str) -> str:
        """Return the object key encoded in ``token`` if it's valid and
        unexpired. Used by the file-serving endpoint to authorize a request."""
        return verify(token, secret=self._signing_secret)
