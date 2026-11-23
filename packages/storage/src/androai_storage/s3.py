"""S3-compatible backend (AWS S3, MinIO, Cloudflare R2, DigitalOcean Spaces, ...).

The bucket must be private. Credentials come from the caller (environment/secret store).
"""

from __future__ import annotations

from typing import BinaryIO

from .base import ObjectInfo, ObjectNotFound, StorageError


class S3Storage:
    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region: str | None = None,
        client=None,
    ):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._c = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region or "us-east-1",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        )

    @staticmethod
    def _check(key: str) -> str:
        if not key or key.startswith("/") or "\x00" in key or ".." in key.split("/"):
            raise StorageError("invalid key")
        return key

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._c.put_object(Bucket=self.bucket, Key=self._check(key), Body=data, **extra)

    def put_file(self, key: str, fileobj: BinaryIO, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._c.upload_fileobj(fileobj, self.bucket, self._check(key), ExtraArgs=extra or None)

    def _get(self, key: str, rng: str | None = None):
        try:
            kw = {"Range": rng} if rng else {}
            return self._c.get_object(Bucket=self.bucket, Key=self._check(key), **kw)["Body"]
        except self._c.exceptions.NoSuchKey as e:
            raise ObjectNotFound(key) from e

    def get_bytes(self, key: str, max_bytes: int | None = None) -> bytes:
        body = self._get(key, f"bytes=0-{max_bytes - 1}" if max_bytes else None)
        return body.read()

    def open_read(self, key: str) -> BinaryIO:
        return self._get(key)  # StreamingBody: file-like with read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._c.head_object(Bucket=self.bucket, Key=self._check(key))
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> None:
        self._c.delete_object(Bucket=self.bucket, Key=self._check(key))

    def list(self, prefix: str) -> list[ObjectInfo]:
        out: list[ObjectInfo] = []
        for page in self._c.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            out.extend(ObjectInfo(o["Key"], o["Size"]) for o in page.get("Contents", []))
        return out

    def delete_prefix(self, prefix: str) -> int:
        if not prefix or prefix == "/":
            raise StorageError("refusing to delete an empty prefix")
        objs = self.list(prefix)
        for i in range(0, len(objs), 1000):
            chunk = objs[i : i + 1000]
            self._c.delete_objects(
                Bucket=self.bucket, Delete={"Objects": [{"Key": o.key} for o in chunk]}
            )
        return len(objs)

    def presigned_get_url(self, key: str, expires_seconds: int = 300, filename: str | None = None) -> str | None:
        params = {"Bucket": self.bucket, "Key": self._check(key)}
        if filename:
            safe = "".join(ch for ch in filename if ch.isalnum() or ch in "._-") or "download"
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        return self._c.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=max(1, min(expires_seconds, 3600))
        )
