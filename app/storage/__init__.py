"""Object-storage client (local | s3) + signed URLs (P1.11).

Core code depends on :class:`~app.storage.base.ObjectStorage`; only
``app/storage/s3.py`` imports ``boto3``, and only when selected via config.
"""

from __future__ import annotations

from app.storage.base import ObjectNotFound, ObjectStorage
from app.storage.factory import build_object_storage

__all__ = [
    "ObjectNotFound",
    "ObjectStorage",
    "build_object_storage",
]
