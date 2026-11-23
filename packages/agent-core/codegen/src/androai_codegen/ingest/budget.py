"""The limits, enforced on the data actually read.

An archive's own claims (entry sizes, compressed sizes) are never trusted: every byte that is
written passes through :meth:`ImportBudget.copy`, which stops as soon as a limit is crossed.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import BinaryIO

from .errors import IngestCode, IngestRejected, shown
from .models import IngestLimits

CHUNK = 64 * 1024


class ImportBudget:
    def __init__(
        self,
        limits: IngestLimits,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        archive_size: int | None = None,
    ) -> None:
        self.limits = limits
        self._monotonic = monotonic
        self._started = monotonic()
        self.archive_size = archive_size  # the archive file's real size, for the overall ratio
        self.files = 0
        self.directories = 0
        self.bytes = 0

    def check_time(self) -> None:
        if self._monotonic() - self._started > self.limits.max_seconds:
            raise IngestRejected(
                IngestCode.TIMEOUT, f"the import took longer than {self.limits.max_seconds:g} s"
            )

    def count_file(self, path: str) -> None:
        self.files += 1
        if self.files > self.limits.max_files:
            raise IngestRejected(
                IngestCode.TOO_MANY_FILES, f"more than {self.limits.max_files} files", shown(path)
            )

    def count_directory(self, path: str) -> None:
        self.directories += 1
        if self.directories > self.limits.max_files:
            raise IngestRejected(
                IngestCode.TOO_MANY_FILES,
                f"more than {self.limits.max_files} directories",
                shown(path),
            )

    def copy(
        self,
        source: BinaryIO,
        target: BinaryIO,
        *,
        path: str,
        compressed_size: int | None = None,
    ) -> tuple[int, str]:
        """Copy ``source`` to ``target`` in chunks. Returns ``(size, sha256)``.

        Refuses, before writing the offending chunk, as soon as this file, the whole import, or the
        compression ratio exceeds its limit. The stream is never read past that point, so an
        endless or lying stream costs at most one extra chunk.
        """
        limits = self.limits
        digest = hashlib.sha256()
        size = 0
        while True:
            self.check_time()
            chunk = source.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            total = self.bytes + size
            if size > limits.max_file_bytes:
                raise IngestRejected(
                    IngestCode.FILE_TOO_LARGE,
                    f"a file is larger than {limits.max_file_bytes} bytes",
                    shown(path),
                )
            if total > limits.max_total_bytes:
                raise IngestRejected(
                    IngestCode.TOTAL_SIZE_EXCEEDED,
                    f"the import is larger than {limits.max_total_bytes} bytes",
                    shown(path),
                )
            if (
                compressed_size is not None
                and size > limits.ratio_floor_bytes
                and size > limits.max_compression_ratio * max(compressed_size, 1)
            ):
                raise IngestRejected(
                    IngestCode.COMPRESSION_RATIO_EXCEEDED,
                    f"an entry expands more than {limits.max_compression_ratio}:1",
                    shown(path),
                )
            if (
                self.archive_size is not None
                and total > limits.ratio_floor_bytes
                and total > limits.max_compression_ratio * max(self.archive_size, 1)
            ):
                raise IngestRejected(
                    IngestCode.COMPRESSION_RATIO_EXCEEDED,
                    f"the archive expands more than {limits.max_compression_ratio}:1",
                    shown(path),
                )
            digest.update(chunk)
            target.write(chunk)
        self.bytes += size
        return size, digest.hexdigest()
