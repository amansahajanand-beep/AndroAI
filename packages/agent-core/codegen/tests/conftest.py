import hashlib
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from androai_codegen.editing import PatchEngine, PatchSet, Workspace

PROJECT = "proj-1"


@pytest.fixture
def ws_root(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def journal_dir(tmp_path: Path) -> Path:
    return tmp_path / "journal"


@pytest.fixture
def workspace(ws_root: Path) -> Workspace:
    return Workspace(ws_root)


@pytest.fixture
def engine(workspace: Workspace, journal_dir: Path) -> PatchEngine:
    return PatchEngine(PROJECT, workspace, journal_dir)


@pytest.fixture
def shadow(workspace: Workspace, tmp_path: Path):
    """A ShadowGit over the workspace, stored outside it. Skips the test if git is missing."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    from androai_codegen.vcs import ShadowGit

    return ShadowGit(workspace, tmp_path / "shadow")


@pytest.fixture
def manager(engine: PatchEngine):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    from androai_codegen.vcs import CheckpointManager

    return CheckpointManager(engine)


@pytest.fixture
def make_dir_link() -> Callable[[Path, Path], bool]:
    """Create a symlink, or an NTFS junction on Windows. Returns False if neither works."""

    def _make(link: Path, target: Path) -> bool:
        try:
            os.symlink(target, link, target_is_directory=True)
            return True
        except (OSError, NotImplementedError):
            pass
        if os.name == "nt":
            done = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                check=False,
            )
            return done.returncode == 0
        return False

    return _make


@pytest.fixture
def sha() -> Callable[[bytes | str], str]:
    def _sha(data: bytes | str) -> str:
        raw = data.encode("utf-8") if isinstance(data, str) else data
        return hashlib.sha256(raw).hexdigest()

    return _sha


@pytest.fixture
def put(ws_root: Path, sha: Callable[[bytes | str], str]) -> Callable[[str, bytes | str], str]:
    """Create a file in the workspace and return its checksum."""

    def _put(rel: str, content: bytes | str) -> str:
        target = ws_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return sha(content)

    return _put


@pytest.fixture
def read(ws_root: Path) -> Callable[[str], bytes | None]:
    """Read a workspace file's bytes, or None if it does not exist."""

    def _read(rel: str) -> bytes | None:
        target = ws_root / rel
        return target.read_bytes() if target.is_file() else None

    return _read


@pytest.fixture
def make_patch() -> Callable[..., PatchSet]:
    def _make(*changes, project_id: str = PROJECT) -> PatchSet:
        return PatchSet(
            project_id=project_id,
            run_id="run-1",
            task_id="task-1",
            description="test patch",
            changes=list(changes),
        )

    return _make
