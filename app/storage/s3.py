"""S3-compatible object storage adapter (P1.11, scaled profile).

Works against AWS S3 or any S3-compatible endpoint (MinIO) via
``endpoint_url`` — the scaled Docker topology runs MinIO locally for exactly
this. Signed URLs use S3's native presigned-URL mechanism; no custom signing
scheme is needed here (contrast with ``app/storage/local.py``).
"""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

from app.storage.base import ObjectNotFound

_NOT_FOUND_CODES = {"NoSuchKey", "404"}


class S3ObjectStorage:
    """S3 implementation of :class:`~app.storage.base.ObjectStorage`."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
                raise ObjectNotFound(key) from exc
            raise
        body: bytes = response["Body"].read()
        return body

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
                return False
            raise
        return True

    def signed_url(self, key: str, *, ttl_s: int = 300) -> str:
        url: str = self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=ttl_s
        )
        return url
