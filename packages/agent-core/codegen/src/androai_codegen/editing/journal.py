"""Durable record of every applied patch, including pre-images so patches can be rolled back.

Layout (outside the workspace, never inside it)::

    <journal>/journal.json                 {"project_id": ...}   guards against reuse
    <journal>/<patch_id>/manifest.json
    <journal>/<patch_id>/diff.patch
    <journal>/<patch_id>/pre/<n>           original bytes of entry n (modify/delete)

The manifest is written last during ``begin``, so a manifest implies complete pre-images.
It is written with status ``applying`` *before* any workspace file is touched, which is what
makes crash recovery possible.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .errors import JournalError, UnknownPatchError
from .fsio import atomic_write_bytes
from .models import JournalEntry, JournalManifest, PatchStatus

_PATCH_ID = re.compile(r"^[0-9a-f]{32}$")
_PREIMAGE = re.compile(r"^pre/[0-9]+$")


def validate_patch_id(patch_id: str) -> str:
    if not isinstance(patch_id, str) or not _PATCH_ID.fullmatch(patch_id):
        raise UnknownPatchError(f"invalid patch id: {patch_id!r}")
    return patch_id


class Journal:
    def __init__(self, root: str | Path, project_id: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._bind_project(project_id)

    def _bind_project(self, project_id: str) -> None:
        marker = self.root / "journal.json"
        if marker.exists():
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise JournalError(f"unreadable journal marker: {marker}") from exc
            if not isinstance(data, dict):
                raise JournalError(f"unreadable journal marker (not an object): {marker}")
            owner = data.get("project_id")
            if owner != project_id:
                raise JournalError(f"journal belongs to project {owner!r}, not {project_id!r}")
        else:
            atomic_write_bytes(marker, json.dumps({"project_id": project_id}).encode("utf-8"))

    def _dir(self, patch_id: str) -> Path:
        return self.root / validate_patch_id(patch_id)

    def begin(self, manifest: JournalManifest, preimages: dict[int, bytes], diff: str) -> None:
        """Persist pre-images, the diff and the manifest. Call before touching the workspace."""
        directory = self._dir(manifest.patch_id)
        for index, data in preimages.items():
            atomic_write_bytes(directory / "pre" / str(index), data)
        atomic_write_bytes(directory / "diff.patch", diff.encode("utf-8"))
        self._write_manifest(manifest)

    def _write_manifest(self, manifest: JournalManifest) -> None:
        payload = manifest.model_dump_json(indent=2).encode("utf-8")
        atomic_write_bytes(self._dir(manifest.patch_id) / "manifest.json", payload)

    def load(self, patch_id: str) -> JournalManifest:
        path = self._dir(patch_id) / "manifest.json"
        if not path.is_file():
            raise UnknownPatchError(f"no such patch: {patch_id}")
        try:
            return JournalManifest.model_validate_json(path.read_bytes())
        except ValueError as exc:
            raise JournalError(f"corrupt manifest for patch {patch_id}") from exc

    def set_status(
        self, patch_id: str, status: PatchStatus, finished_at: datetime | None = None
    ) -> JournalManifest:
        updated = self.load(patch_id).model_copy(
            update={"status": status, "finished_at": finished_at}
        )
        self._write_manifest(updated)
        return updated

    def list_patches(self) -> list[JournalManifest]:
        manifests: list[JournalManifest] = []
        for child in self.root.iterdir():
            # A directory without a manifest means begin() never finished, so the workspace
            # was never touched. Those are ignored.
            if (
                child.is_dir()
                and _PATCH_ID.fullmatch(child.name)
                and (child / "manifest.json").is_file()
            ):
                manifests.append(self.load(child.name))
        return sorted(manifests, key=lambda m: m.created_at)

    def scan(self) -> tuple[list[JournalManifest], dict[str, str]]:
        """Like :meth:`list_patches`, but a corrupt record is reported instead of raised.

        Returns ``(manifests, unreadable)`` where ``unreadable`` maps patch id to the reason.
        Used by crash recovery, where one damaged record must not hide the others.
        """
        manifests: list[JournalManifest] = []
        unreadable: dict[str, str] = {}
        for child in self.root.iterdir():
            if (
                child.is_dir()
                and _PATCH_ID.fullmatch(child.name)
                and (child / "manifest.json").is_file()
            ):
                try:
                    manifests.append(self.load(child.name))
                except (JournalError, OSError) as exc:
                    unreadable[child.name] = str(exc)
        return sorted(manifests, key=lambda m: m.created_at), unreadable

    def read_preimage(self, patch_id: str, entry: JournalEntry) -> bytes:
        if entry.preimage is None or not _PREIMAGE.fullmatch(entry.preimage):
            raise JournalError(f"entry for {entry.path} has no valid pre-image")
        return (self._dir(patch_id) / entry.preimage).read_bytes()

    def read_diff(self, patch_id: str) -> str:
        return (self._dir(patch_id) / "diff.patch").read_text(encoding="utf-8")
