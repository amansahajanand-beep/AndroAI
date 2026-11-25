import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CODEGEN = ROOT / "packages" / "agent-core" / "codegen"
for path in (
    CODEGEN / "src",
    CODEGEN / "tests",
    Path(__file__).resolve().parents[1] / "src",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
