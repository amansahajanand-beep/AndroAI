from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol


class StorageError(Exception):
    pass


class ObjectNotFound(StorageError):
    pass


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int


class ObjectStorage(Protocol):
    """Private object store. Objects are never publicly readable; access is through
    the API or short-lived signed URLs (`presigned_get_url`, S3 only)."""

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    def put_file(self, key: str, fileobj: BinaryIO, content_type: str | None = None) -> None: ...

    def get_bytes(self, key: str, max_bytes: int | None = None) -> bytes: ...

    def open_read(self, key: str) -> BinaryIO: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def delete_prefix(self, prefix: str) -> int: ...

    def list(self, prefix: str) -> list[ObjectInfo]: ...

    def presigned_get_url(self, key: str, expires_seconds: int = 300, filename: str | None = None) -> str | None:
        """Short-lived download URL, or None if this backend cannot sign (caller streams)."""
        ...
