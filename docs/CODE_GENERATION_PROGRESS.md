# Code Generation Progress (Person 3)

Scope: `packages/agent-core/codegen` (library, `androai_codegen`) and `workers/ai-agent` (Celery adapter).

| Phase | Scope | State |
|---|---|---|
| 0 | Package setup, dev environment, this document | Done |
| 1 | File-editing abstraction and patch engine | **Done, verified on Windows only** (see Verification) |
| 2 | Git checkpoints, manual vs AI change tracking | **Done, verified on Windows only** (see Verification) |
| 3 | Contracts proposal for `CodingTask` / `CodingResult` | **Drafted, awaiting Persons 2 and 4**: [CODEGEN_CONTRACT_PROPOSAL.md](CODEGEN_CONTRACT_PROPOSAL.md). No contracts PR until both approve. |
| 4 | Code review engine | **In progress. 4a done** (syntax, imports, duplicates, resources, patch review), verified on Windows only. **4b not started**: manifest, navigation, dependencies, security, API usage, null safety, change-aware rules. |
| 5 | New project generation | Not started |
| 6 | Existing project modification | Not started |
| 7 | Self-healing repair | Not started |
| 8 | Visual editor source mapping | Not started |

The Celery adapter in `workers/ai-agent` is still the foundation skeleton. Nothing consumes `CodingTask` yet.

## Patch architecture (implemented)

```
PatchSet ──► preview()/apply() ──► plan (pure, in memory)
                                     │ blocking problems? ──► PatchRejected (nothing written)
                                     ▼
                     journal.begin: pre-images + diff + manifest(status=applying)
                                     ▼
                     write files atomically, one at a time
                       │ any failure ──► undo all writes ──► PatchApplyError(rolled_back=…)
                                     ▼
                     manifest status = applied   ──►  ApplyResult (records + diff reference)

rollback(patch_id)  ──► refuses if any file changed after the patch (RollbackConflict)
recover()           ──► undoes patches stuck in "applying" after a crash
```

- **Models** (`androai_codegen.editing.models`): `PatchSet` of `CreateFile` / `ModifyFile` / `DeleteFile`.
  `ModifyFile` uses exact-text `TextEdit`s (preferred) or full `content`, and **requires**
  `expected_checksum`, the version the author read.
- **Audit trail**: every file change becomes a `ChangeRecord` carrying project ID, run ID, task ID, path,
  previous checksum, new checksum and description. Records are persisted in the journal and queryable
  with `engine.history(path)`.
- **Journal** lives outside the workspace (`<journal>/<patch_id>/{manifest.json,diff.patch,pre/*}`) and is
  bound to one project ID.
- **Internal models only.** The engine does not import `androai_contracts`. The worker adapter will map
  to contracts, so contract changes never touch the engine.

```python
engine = PatchEngine("proj-1", Workspace(project_dir), journal_dir)
baseline = engine.snapshot(["app/src/Main.kt"])            # when the task starts
text = engine.read_for_llm("app/src/Main.kt").content      # masked; protected files refused
preview = engine.preview(patch)                            # dry run: problems + diff, no writes
result = engine.apply(patch, approved_deletions=[...])     # atomic; raises PatchRejected on problems
engine.rollback(result.patch_id)
```

## File safety (implemented, each rule has tests)

| Rule | Behaviour |
|---|---|
| Never overwrite manual changes | Modify/delete compare the current checksum with `expected_checksum`; mismatch is a `conflict` that blocks the **whole** patch. Create refuses to overwrite an existing file. |
| Rollback never discards later edits | `rollback` fails with `RollbackConflict` (nothing touched) if any file changed after the patch. |
| Atomic patches | Everything is validated in memory first; a write failure restores all files, including directories the patch created. `KeyboardInterrupt` restores and re-raises. |
| Crash safety | Pre-images and the manifest are persisted before the first write; `recover()` restores, but leaves anything that is neither original nor patched content and reports it. |
| Path safety | Rejects `..`, absolute paths, backslashes, drive letters / `:`, control characters, Windows reserved names, trailing dots/spaces, any `.git` (incl. `GIT~1`), symlinks and junctions in the path, anything resolving outside the workspace. |
| Project isolation | An engine is bound to one project ID; patches for another project and journals of another project are rejected. |
| Approval for destructive changes | Deletion needs explicit per-path approval (`approved_deletions`); otherwise `requires_approval` is reported and nothing is deleted. |
| Protected files | Keystores, `*.pem`, `keystore.properties`, `local.properties`, `.env*`, service-account JSON: cannot be created, modified, deleted or shown to an LLM. |
| Secrets | `read_for_llm` masks likely secrets. A patch that writes the `[REDACTED]` marker is rejected, so masked text can never replace a real secret. |
| Limits | 2 MiB per file and 500 files per patch by default (configurable). |
| Concurrency | Per-journal file lock; a second writer gets `WorkspaceBusyError`. |
| Text handling | CRLF files stay CRLF; UTF-8 BOM preserved; file permission bits preserved. |

## Version control (implemented, Phase 2)

`androai_codegen.vcs`: checkpoints, diffs, change summaries, restore, file history, and manual-vs-AI
attribution. The platform's shared Git service does not exist yet, so this is a local implementation behind
the `VersionControl` protocol (the seam to swap if a shared service appears).

**Design: a shadow repository** outside the workspace (`<journal>/vcs`, used as
`git --git-dir=<shadow> --work-tree=<workspace>`). The project's own `.git`, branch, index, hooks and config
are never read or written, nothing is ever committed or pushed to the user's repository, and it behaves the
same whether or not the workspace is a git repository.

```
CheckpointManager.apply(patch)
  1. record edits nobody told us about        -> commit, origin = manual
  2. PatchEngine.apply(patch)                 (Phase 1: validated, atomic)
  3. record only the files the engine wrote,
     and only if still exactly as written     -> commit, origin = ai
checkpoint(label)    records pending manual edits first, then marks the current state
restore(checkpoint)  reverts only files the AI changed since; never files changed by hand
```

| Capability | API |
|---|---|
| Checkpoint | `manager.checkpoint(label, run_id=, task_id=)` |
| Diff / summary since a checkpoint (includes unrecorded manual edits) | `manager.diff_since(id)`, `manager.summary_since(id)` (`ChangeSummary.text`: "3 files changed, +40 -5") |
| Manual vs AI tracking | `manager.pending_changes()`, per-commit `origin` (`baseline` / `manual` / `ai` / `rollback`) |
| File-level history | `manager.file_history(path)`: origin, status, run, task, patch id |
| Rollback | `manager.restore(id, run_id=, task_id=, skip_conflicts=False)` |

**Restore rules.** Only files the AI changed after the checkpoint are touched, and only if nobody changed
them by hand afterwards. If a file was changed by both, restoring it would lose the manual work: by default
nothing is touched and `RestoreConflict` is raised; with `skip_conflicts=True` the conflicting files are kept
as they are and the rest are restored. Restores run through the Phase 1 engine, so they are atomic, journaled
and themselves reversible with `engine.rollback`, and they write the checkpoint's exact bytes (line endings
included). Files the AI created are deleted on restore without a prompt, because the checks above prove
nobody else edited them.

| Rule | Behaviour |
|---|---|
| No cross-contamination | Inherited `GIT_*` environment is dropped, global/system config disabled, hooks disabled, workspace `.gitattributes` neutralised (no line-ending or filter conversion), `GIT_TERMINAL_PROMPT=0`. |
| Secrets stay out | Protected files, oversized files (>10 MiB), symlinks and unsafe paths are never staged, so they are not copied into the shadow repo or shown in diffs. Diffs are masked by default. |
| Unforgeable provenance | Commit messages are written only by this code; free text is single-line, only the last paragraph is parsed, unknown provenance is treated as manual. |
| Injection | Only full commit ids or `HEAD` reach git; paths are normalized; arguments are never passed through a shell. |
| Attribution race | A file edited again right after the engine wrote it is not claimed by the AI; it stays pending and is recorded as manual. |
| Failure honesty | If the patch applied but could not be recorded, `TrackingError` carries the patch id so it can still be rolled back. |
| Concurrency | `.vcs.lock` per journal (always taken before the engine lock). |

All AI writes must go through `CheckpointManager`; see the limitations below.

## Code review engine (Phase 4a implemented)

`androai_codegen.review`: static review of Kotlin, Java, XML, manifest and Gradle files. It **never compiles or
runs anything and never claims the code works**: every report carries `scope = "static"` and its limitations.

```python
review = review_patch(engine, patch)     # nothing is written; reviews the project as it WOULD become
review.applicable                        # the patch is valid and nothing blocking was found
review.report.findings                   # severity, rule, file, line, description, suggested_fix, blocking
ReviewEngine().review(after, before=before)   # or review two project states directly
```

- **Regression-aware.** With a `before` state only findings the change introduced are reported; existing ones
  are counted in `preexisting_suppressed`. Identity is rule + file + symbol, so moving a line does not make an
  old finding new.
- **No cascades.** One malformed `strings.xml` is one finding, not an "unresolved `@string/x`" at every use.
- **Safe on untrusted input.** Reads text only and executes nothing; protected files are never opened; XML with
  DOCTYPE/entities is rejected (no expansion attacks); the lexer is linear-time (tested on pathological input);
  caps on files, bytes and findings; a crashing rule group becomes a finding, not a failed review.
- **Findings are shaped like the proposed contract's `ReviewFinding`**, so mapping is mechanical.

| Category | Rules implemented in 4a |
|---|---|
| syntax | unterminated string / comment / char literal; unbalanced brackets (names the bracket that is still open and its line); malformed XML; malformed TOML |
| imports | missing import (project symbols, about 250 curated Android/Compose/AndroidX/Kotlin names, Compose extension functions, `.dp`/`.sp`, `by` state delegates, icons, coroutine builders); missing `R` import; unresolved project import (member imports and generated classes are accepted); conflicting / duplicate imports; duplicate class; unresolved `Foo::class` |
| resources | unresolved `R.type.name` and `@type/name` with a "did you mean" hint; duplicate resources per directory; invalid resource names. Library, framework (`@android:`) and theme-attribute references are not flagged |

**Not implemented yet (4b):** manifest rules, navigation, dependency/Gradle rules, security, incorrect API use,
null safety, and the change-aware "unintended changes" rules (removed components/permissions/dependencies,
package or application-id changes, language/UI conversions). Review against a checkpoint
(`CheckpointManager`) is also not wired up.

## Generation workflow, supported technologies, repair rules

**Not implemented yet** (Phases 5-8). Planned per the Role 3 spec: Kotlin first with Jetpack Compose, then
Java and XML layouts, and a repair loop bounded by iteration, time, cost, repeated-error and no-progress
limits, returning infrastructure and provider failures to orchestration without touching source.
The patch engine is language-agnostic: it edits UTF-8 text files and knows nothing about Kotlin or Gradle.

## Verification

Run on Windows 10, Python 3.12.10, in `.venv` at the repo root:

| Check | Result |
|---|---|
| `pytest packages/agent-core/codegen` | 394 passed, 5 skipped (about 105 s: the VCS tests spawn git) |
| `pytest packages/contracts` (untouched) | 2 passed |
| `ruff check` / `ruff format --check` | clean |
| CI import check for all four workers, alongside `androai_codegen` | OK (last run before Phase 4) |
| Mutation check, Phase 1: 16 safety mechanisms disabled one at a time | All 16 caught (first run caught 15; the 16th, workspace containment, got its own test) |
| Mutation check, Phase 2: 16 more | All 16 caught (first run caught 15; the survivor was "only the last paragraph of a commit message is trusted", now has its own test) |
| Mutation check, Phase 4a: 22 review rules/engine behaviours | All 22 caught (first run: 17 caught, 2 survivors that exposed tests which could not tell the difference, 2 stale patterns; fixed and re-run clean) |

Real bug found by these tests: `pending_changes()` intermittently missed same-size manual edits (**25 of 60**
trials inconsistent). Cause: it stages into a throwaway copy of git's index, and `shutil.copyfile` gave the copy
a fresh mtime, which defeats git's "racily clean" protection (Git for Windows compares file times at one-second
granularity). A missed manual edit could later have been discarded by a restore. Fixed with `shutil.copy2`;
**0 of 60** after, with a deterministic regression test that fails on the old code.

Real bugs the Phase 4a tests found (all fixed, each with a regression test):

- **CRLF files broke import parsing.** Found by accident through a test fixture: with Windows line endings no
  import was recognized, so everything looked "missing" (8 false errors in one file). Most Windows-edited
  projects are CRLF. Sources and Gradle scripts are now normalized to LF first; the whole known-good project
  is tested again as CRLF, and the test is proven to fail when the fix is removed.
- A malformed resource file made every reference to it "unresolved" (cascade).
- Duplicate classes/resources were reported only on the file that sorts later, which can blame the old file
  for a duplicate a new file introduced; now every involved file is reported.
- `sealed class A { object B : A() }` lost `B`'s supertype (header scan did not stop at `}`).
- Treating every `Theme.*` as a library style would have hidden the common mistake of referencing an app theme
  that was never defined; only library-specific prefixes are skipped now.

Git used: 2.56.1 (Windows). The 5 skipped tests are 2 POSIX-permission-bit tests, 1 POSIX-only file-name test
(none apply on Windows) and 2 plain-symlink tests (this account cannot create symlinks). The equivalent NTFS
**junction** tests did run.

**Never run on Linux or in CI**, which is where the workers run. POSIX code paths (permission bits, symlinks,
`fcntl`-based locking inside `filelock`) and other git versions are untested. Git's timestamp handling differs
between platforms, which is exactly the area where the bug above lived.

## Known limitations

- Atomicity is logical (journal + undo), not a filesystem transaction. A hard kill between two file writes
  leaves a partial state until `recover()` runs at the next start-up. Workers should call it at boot.
  A hard kill can also leave a `.androai-*.tmp` file in the workspace.
- One journal per workspace. The lock lives in the journal directory, so two engines with different
  journals on the same workspace are not serialized. Writers outside the engine can still race it (TOCTOU).
- UTF-8 text only. Binary files cannot be created or modified (images, fonts need a separate path later).
- No rename/move primitive: delete + create, so a rename needs deletion approval.
- Line endings follow the file's dominant style; mixed-ending files may get normalized by edits.
- The engine's own diff is informational (review and audit), not guaranteed `git apply`-able. Use the Phase 2
  git diffs (`diff_since`) where a standard diff is needed.
- Secret masking is best-effort and over-masks (e.g. `token_url = "https://..."`).
- `.git` protection does not cover macOS HFS+ ignorable-Unicode aliases.
- Journals are never cleaned up.
- Cross-file import/reference updates are language-aware and come with Phases 5-6.

Phase 2 (version control):

- **All AI writes must go through `CheckpointManager`.** A write through a bare `PatchEngine` is
  indistinguishable from a manual edit, is recorded as manual, and so `restore` will not undo it.
- Manual edits are attributed when the manager next runs, not when they happened.
- Git's stat cache cannot see an edit that keeps both a file's size and its modification time unchanged when the
  file is older than the last snapshot (only possible deliberately, e.g. `touch -r`). Same-size edits made within
  the same second as a snapshot are handled (that was the bug above).
- Not tracked, so invisible to checkpoints, diffs and restore: protected files, symlinks, files over 10 MiB,
  `.gradle/ build/ .idea/ .cxx/ captures/ *.apk *.aab *.iml`, files matching the project's `.gitignore` (unless
  the engine wrote them), and permission-bit-only changes.
- Restore handles UTF-8 text files only; others are reported as conflicts. Binary files cannot be restored.
- The shadow repository is local, linear and never pruned (`gc.auto=0`). Checkpoint metadata lives in JSON files
  next to it, not in git.
- Requires `git` on `PATH`. The ai-agent image (`python:3.12-slim`) has no git (see below).

Phase 4 (code review):

- **Never validated on a real-world project.** The only inputs so far are a hand-written 18-file Compose app
  (which must produce zero findings) and one-fault-at-a-time breakages of it. The false-positive rate on real
  code is unknown; running it over real projects is the first thing to do before trusting a blocking finding.
- **Not a compiler.** A name that is neither declared in the project nor in the curated list is never reported;
  type inference, overload resolution and most generics are out of reach. No finding does not mean it compiles.
- The curated tables (about 250 names, a few dozen library mappings) only list names that really need an
  import; coverage is incomplete by design, and a wrong entry would flag correct code.
- Compose-specific import rules apply to Kotlin only; Java files get type-import checks only.
- Declarations are found lexically: nested class names are exact only one level deep, and unusual formatting
  can hide a declaration.
- Multi-module projects are treated as one: resources and dependencies are looked up project-wide (permissive).
- Resource types a library may legitimately provide (`style`, and names with library prefixes) are skipped, so
  a typo in such a name is not caught.

## Needs action from other owners

- **Person 4 (CI, Makefile, `packages/contracts`)**: `.github/workflows/ci.yml` and the `Makefile` do not
  install or test codegen. Suggested lines: add `-e "packages/agent-core/codegen[dev]"` to the install steps
  and `packages/agent-core/codegen` to the `pytest` paths. CI would also give the missing Linux coverage.
- **Persons 2 and 4 (contracts)**: current `CodingTask` / `CodingResult` do not carry what the Role 3 spec
  needs: task type, implementation plan, constraints, validation requirements, repair inputs (classified
  errors, build/test results, budget) on the way in; modified/created/deleted split, diff reference, review
  findings, repair summary, `requires_approval` on the way out. `CodingResult.files` carries full file
  content, which conflicts with patch-based editing and the "services exchange keys, not blobs" rule.
  The proposal is in [CODEGEN_CONTRACT_PROPOSAL.md](CODEGEN_CONTRACT_PROPOSAL.md) (10 decisions listed up front);
  changes need producer and consumer approval and a `SCHEMA_VERSION` bump.
- **Person 3 (me, later)**: `workers/ai-agent/Dockerfile` must also copy and install
  `packages/agent-core/codegen` once the worker depends on it, and install `git` (`apt-get install -y git`).
  Not done yet because nothing in the worker imports codegen.
- **Repository owner (`amansahajanand-beep`)**: `git push --dry-run origin p3/codegen-foundation` from this
  checkout returns HTTP 403 ("Permission to amansahajanand-beep/AndroAI.git denied to
  vinayaksahajanand-cell"). Nothing from this branch can be pushed until that account is granted write access
  or a fork + pull request flow is used. Phases 0-2 are committed locally (`ab95991` on
  `p3/codegen-foundation`); nothing has been pushed.
