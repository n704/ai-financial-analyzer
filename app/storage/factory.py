"""Config → concrete object storage adapter (P1.11) — same pattern as the
provider/infra factories: the one place ``object_storage.provider`` maps to a
concrete class. ``boto3`` is imported only when ``s3`` is selected.
"""

from __future__ import annotations

import os

from app.config import ConfigError, Settings
from app.storage.base import ObjectStorage


def build_object_storage(settings: Settings) -> ObjectStorage:
    cfg = settings.object_storage

    if cfg.provider == "local":
        from app.storage.local import LocalObjectStorage

        if not cfg.path:
            raise ConfigError("object_storage.provider='local' requires object_storage.path")
        secret = cfg.resolve_signing_secret().get_secret_value()
        return LocalObjectStorage(root=cfg.path, signing_secret=secret)

    if cfg.provider == "s3":
        from app.storage.s3 import S3ObjectStorage

        if not cfg.bucket:
            raise ConfigError("object_storage.provider='s3' requires object_storage.bucket")
        endpoint_url = os.environ.get(cfg.endpoint_env) if cfg.endpoint_env else None
        return S3ObjectStorage(
            bucket=cfg.bucket,
            endpoint_url=endpoint_url,
            region=cfg.region,
            access_key=os.environ.get(cfg.access_key_env),
            secret_key=os.environ.get(cfg.secret_key_env),
        )

    raise ConfigError(
        f"object_storage.provider={cfg.provider!r} is not implemented yet "
        f"(supported now: local, s3)"
    )
