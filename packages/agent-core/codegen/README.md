# packages/agent-core/codegen

Android code generation, editing, review and repair engine. Pure Python library; it has no
Celery/Redis dependency. The Celery adapter lives in `workers/ai-agent`.

- Owner: **Person 3**
- Package: `androai_codegen` (src layout)
- Must not import `agent-core/orchestration`. Cross-service data goes through `packages/contracts`.

## Modules

| Module | Purpose | State |
|---|---|---|
| `androai_codegen.editing` | Safe multi-file patch engine: path validation, checksums, conflict detection, atomic apply, rollback, journal | Phase 1 |
| `androai_codegen.vcs` | Shadow-git checkpoints, diffs, summaries, file history, manual-vs-AI tracking, manual-change-safe restore. Needs `git` on PATH | Phase 2 |
| `androai_codegen.review` | Static review of Kotlin/Java/XML/Gradle: syntax, imports, duplicates, resources, manifest, dependencies, and what a change removed or altered; reviews a patch before it is applied, or the workspace against a checkpoint. Never compiles or runs code | Phase 4a, 4b-1 |
| `androai_codegen.templates` | Android project templates rendered as a `PatchSet` (Kotlin + Jetpack Compose, single module): validated `ProjectConfig` in, deterministic files out; applying is the patch engine's job. The default project's **debug build was verified once** with Gradle (see `VERIFIED_BUILD` in `templates/versions.py` for exactly what that covers; release, lint, tests and emulator were not run) | Phase 5.1 |

See [docs/CODE_GENERATION_PROGRESS.md](../../../docs/CODE_GENERATION_PROGRESS.md) for architecture,
safety rules, verification status and known limitations.

## Develop

```bash
python -m venv .venv                      # repo root, same venv the Makefile uses
.venv/Scripts/python -m pip install -e packages/contracts -e "packages/agent-core/codegen[dev]"
.venv/Scripts/python -m pytest packages/agent-core/codegen
.venv/Scripts/python -m ruff check packages/agent-core/codegen
```
