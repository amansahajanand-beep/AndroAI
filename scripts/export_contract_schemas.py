"""Export JSON Schema for every contract to packages/contracts/schemas/.

Non-Python consumers (e.g. the web app) generate their types from these files.
Run: python scripts/export_contract_schemas.py
"""

import json
from pathlib import Path

import androai_contracts as c

MODELS = [
    c.AgentTask, c.AgentTaskStatus, c.CodingTask, c.CodingResult,
    c.BuildJob, c.BuildResult, c.TestJob, c.TestResult,
]

out = Path(__file__).resolve().parents[1] / "packages" / "contracts" / "schemas"
out.mkdir(parents=True, exist_ok=True)
for m in MODELS:
    (out / f"{m.__name__}.json").write_text(
        json.dumps(m.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
print(f"wrote {len(MODELS)} schemas to {out}")
