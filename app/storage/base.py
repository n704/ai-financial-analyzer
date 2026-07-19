"""Object storage protocol (P1.11): put/get/delete + signed-URL generation.

Same pattern as the provider/infra protocols — core code depends on
``ObjectStorage``, never on ``boto3`` or raw filesystem calls. Local disk is the
default backend; S3 (or any S3-compatible endpoint, e.g. MinIO) is the scaled
option, selected in config (SPEC.md §4).

Synchronous by design: both backends' underlying I/O (disk, boto3) is
naturally sync. Call sites in async request handlers should offload with
``starlette.concurrency.run_in_threadpool`` (or equivalent) rather than block
the event loop — that's a call-site concern, not this interface's.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class ObjectNotFound(Exception):
    """Raised by ``get``/``delete`` when ``key`` doesn't exist."""

    def __init__(self, key: str) -> None:
        super().__init__(f"object not found: {key!r}")
        self.key = key


@runtime_checkable
class ObjectStorage(Protocol):
    """Private object storage keyed by an opaque string path
    (``{user_id}/{document_id}.pdf`` per ARCHITECTURE.md §5). Objects are never
    served directly — only through a short-lived ``signed_url``."""

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        """Write (or overwrite) the object at ``key``."""
        ...

    def get(self, key: str) -> bytes:
        """Read the object at ``key``. Raises :class:`ObjectNotFound` if absent."""
        ...

    def delete(self, key: str) -> None:
        """Remove the object at ``key``. Idempotent — missing key is not an error."""
        ...

    def exists(self, key: str) -> bool: ...

    def signed_url(self, key: str, *, ttl_s: int = 300) -> str:
        """A short-lived URL granting read access to ``key`` for ``ttl_s``
        seconds — S3 uses native presigned URLs; local storage self-issues an
        HMAC-signed token (see ``app/storage/signing.py``)."""
        ...
