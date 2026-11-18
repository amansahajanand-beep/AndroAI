from pathlib import Path

from androai_orchestration.config import WorkerConfig

EXAMPLE = Path(__file__).resolve().parents[1] / "providers.example.json"


def test_example_config_is_valid():
    cfg = WorkerConfig.load(str(EXAMPLE))
    assert cfg.llm.routes and cfg.limits.max_repair_attempts == 3
    assert all(not m.priced for m in cfg.llm.models)  # prices must be filled in per deployment
