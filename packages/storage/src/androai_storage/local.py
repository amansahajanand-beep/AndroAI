"""Filesystem backend for development and tests. Not for multi-node production."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

from .base import ObjectInfo, ObjectNotFound, StorageError


class LocalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not key or key.startswith("/") or "\\" in key or "\x00" in key or ".." in key.split("/"):
            raise StorageError("invalid key")
        p = (self.root / key).resolve()
        if self.root != p and self.root not in p.parents:
            raise StorageError("key escapes storage root")
        return p

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def put_file(self, key: str, fileobj: BinaryIO, content_type: str | None = None) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        with tmp.open("wb") as out:
            shutil.copyfileobj(fileobj, out, 1024 * 1024)
        tmp.replace(p)

    def get_bytes(self, key: str, max_bytes: int | None = None) -> bytes:
        p = self._path(key)
        if not p.is_file():
            raise ObjectNotFound(key)
        with p.open("rb") as f:
            return f.read(max_bytes) if max_bytes is not None else f.read()

    def open_read(self, key: str) -> BinaryIO:
        p = self._path(key)
        if not p.is_file():
            raise ObjectNotFound(key)
        return p.open("rb")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> int:
        n = len(self.list(prefix))
        base = self._path(prefix.rstrip("/"))
        if base.is_dir():
            shutil.rmtree(base)
        elif base.is_file():
            base.unlink()
        return n

    def list(self, prefix: str) -> list[ObjectInfo]:
        base = self._path(prefix.rstrip("/"))
        if not base.exists():
            return []
        files = [base] if base.is_file() else [f for f in base.rglob("*") if f.is_file()]
        return [
            ObjectInfo(key=f.relative_to(self.root).as_posix(), size=f.stat().st_size)
            for f in files
            if not f.name.endswith(".tmp")
        ]

    def presigned_get_url(self, key: str, expires_seconds: int = 300, filename: str | None = None) -> str | None:
        return None
