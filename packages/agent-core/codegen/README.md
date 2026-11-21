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
| `androai_codegen.templates` | Android project templates rendered as a `PatchSet` (Kotlin + Jetpack Compose, single module): validated `ProjectConfig` in, deterministic files out; applying is the patch engine's job. The default project's **debug build, release build, AAB and lint were verified** with Gradle (see `VERIFIED_BUILD` in `templates/versions.py` for exactly what ran; the release outputs are unsigned, the app without a spec has no unit tests, and no other configuration was tested) | Phase 5.1 |
| `androai_codegen.templates` (`ProjectSpec`) | Phase 5.2: a structured, validated `ProjectSpec` (screens, texts, navigation buttons) rendered into a multi-screen project by `render_patch(config, spec=...)`: deterministic, no LLM, `const val` routes that the static navigation rules can follow. Debug and release builds, AAB and lint were verified on four sample specs; the three-screen sample was also run on one Android 17 emulator (navigation, Back, rotation, logcat), the outputs are unsigned | Phase 5.2 |
| `androai_codegen.templates` (navigation tests) | Phase 5.3: a project rendered from a `ProjectSpec` also gets a generated JVM `NavigationTest` (Robolectric + Compose test + Navigation test helper) and its test-only dependencies; the tests were run with Gradle on four sample specs and fail when the generated navigation is broken (mutation-checked). They run on a simulated Android 15 (API 35) on JDK 17, and a project with `minSdk` above 35 gets none (see "Generated navigation tests") | Phase 5.3 |
| `androai_codegen.templates` (scrolling) | Phase 5.4: generated screens scroll vertically (an 8-button screen was unreachable in landscape on an emulator before the fix, reachable after); the tests scroll to what they tap, no longer need a tall test screen and run on the debug and the release unit-test task; signing was only investigated (throwaway key, nothing generated); Compose previews are not verified | Phase 5.4 |

See [docs/CODE_GENERATION_PROGRESS.md](../../../docs/CODE_GENERATION_PROGRESS.md) for architecture,
safety rules, verification status and known limitations.

## Develop

```bash
python -m venv .venv                      # repo root, same venv the Makefile uses
.venv/Scripts/python -m pip install -e packages/contracts -e "packages/agent-core/codegen[dev]"
.venv/Scripts/python -m pytest packages/agent-core/codegen
.venv/Scripts/python -m ruff check packages/agent-core/codegen
```
