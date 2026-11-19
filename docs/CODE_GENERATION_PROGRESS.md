# Code Generation Progress (Person 3)

Scope: `packages/agent-core/codegen` (library, `androai_codegen`) and `workers/ai-agent` (Celery adapter).

| Phase | Scope | State |
|---|---|---|
| 0 | Package setup, dev environment, this document | Done |
| 1 | File-editing abstraction and patch engine | **Done, hardened (`5aea805`), verified on Windows and Linux (WSL); not yet in CI** (see Verification) |
| 2 | Git checkpoints, manual vs AI change tracking | **Done, verified on Windows and Linux (WSL); not yet in CI** (see Verification) |
| 3 | Contracts proposal for `CodingTask` / `CodingResult` | **Drafted, awaiting Persons 2 and 4**: [CODEGEN_CONTRACT_PROPOSAL.md](CODEGEN_CONTRACT_PROPOSAL.md). No contracts PR until both approve. |
| 4 | Code review engine | **In progress. 4a done** (syntax, imports, duplicates, resources, patch review), verified on Windows and Linux (WSL) against synthetic fixtures and, on Windows, two real projects (`nowinandroid`: 0 findings, 9 of 9 injected faults caught; `AntennaPod`, Java/Groovy: 2 findings, 10 of 10 caught). **4b not started**: manifest, navigation, dependencies, security, API usage, null safety, change-aware rules. |
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

Results below are for `p3/review-engine` (Phase 4a, the patch-engine hardening and the real-project fixes).

| Platform | Commit | `pytest packages/agent-core/codegen` | Ruff |
|---|---|---|---|
| Windows 10, Python 3.12.10, Git 2.56.1 | `ce547ad` (code of the latest commit) | **454 passed, 5 skipped, 1 xfailed** (about 1 min: the VCS tests spawn git) | `ruff check` clean; `ruff format --check` clean (53 files); `compileall` clean |
| Linux (WSL Ubuntu, kernel 6.18 WSL2, Python 3.14.4, git 2.53.0, ext4), `git archive` export | `ce547ad` | **458 passed, 1 skipped, 1 xfailed** (about 15 s) | `ruff check` clean; `ruff format --check` clean (53 files); `compileall` clean |
| Linux (same) | `6dfb196` | 442 passed, 1 skipped | clean (52 files) |
| Windows | `6dfb196` | 438 passed, 5 skipped | clean (52 files) |
| Windows / Linux | `5aea805` | 410 passed, 5 skipped / 414 passed, 1 skipped | clean |

The Linux commands were: `git archive` of the commit, `tar -xf` into a fresh directory on ext4,
`python3 -m venv --without-pip`, pip bootstrapped from the bundled wheel, `pip install -e packages/contracts -e
"packages/agent-core/codegen[dev]"`, then `pytest -q -rs`, `ruff check .`, `ruff format --check .` and
`python -m compileall -q src tests`, all from `packages/agent-core/codegen`; every step exited 0. The only Linux
skip is the Windows-only NTFS-junction test; the 4 tests that skip on Windows (permission bits, NTFS-only names,
symlinks) pass on Linux. The documentation-only commit after `ce547ad` does not change any tested file.
The `xfailed` is a strict expected failure that records a known limitation (see Phase 4 limitations).

| Other check | Result |
|---|---|
| `pytest packages/contracts` (untouched) | 2 passed |
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

### Real-project validation (review engine)

Run over Google's open-source `android/nowinandroid` (commit `2982e63`, 715 files, 310 Kotlin files, 35 Gradle
modules, convention plugins, version catalog, protobuf, Room, Hilt, Compose, Navigation 3) in a disposable
clone; the clone was verified byte-for-byte unchanged afterwards and all fault injection used copies.

| Check | First run | After fixes |
|---|---|---|
| Blocking findings on code that compiles in upstream CI | **34** (all false positives) | **0** |
| Faults injected into real code that the 4a rules should catch (missing/typo import, unbalanced bracket, unterminated string, unresolved `R.string` and `@string`, duplicate class, duplicate resource, library import removed) | 9 of 9 | 9 of 9 |
| A CRLF copy of the whole project | identical findings | identical findings |
| Patch review (benign edit, removed import, new file with unbalanced bracket, approved delete of a widely imported class, unapproved delete, stale checksum, protected file) | correct | correct; the workspace was byte-identical afterwards |
| Parsed facts | 26 manifests and their launcher/permissions/components, 31 namespaces from Gradle, 103 catalog libraries, 147 catalog dependencies (matches an independent count) | modules 37 -> **35** (exact), `libs.bundles.*` resolved, `custom_catalogs` correct |
| Review time | about 1.5 s per full review | same |

The 34 false positives and their fixes (each with a regression test and a twin proving the real error is
still reported, in `tests/test_review_realworld.py`):

- A project that adds helpers to a library's package (`package androidx.test.uiautomator`) made the library's
  own classes look unresolved (17). Packages under framework roots, curated library packages or a declared
  dependency's Maven group are no longer treated as project-only.
- Classes generated from `.proto` files (5): `.proto` files are now read (`java_package`,
  `java_multiple_files`, `java_outer_classname`, top-level messages/enums/services).
- Nested members of the generated `R` class, e.g. `import ns.R.string` (5).
- The same icon name imported from two style packages (`outlined.Bookmarks`, `rounded.Bookmarks`) is not a
  conflict, and the second import no longer hides the first (4).
- `rule.apply { setContent {} }`: a bare `setContent` inside an `apply`/`run`/`with` block may be a member of the
  receiver (1).
- Words inside a backtick test name read as code (1), which also unbalanced brackets.
- A comment-only license-header XML outside `res/` and the manifest reported as malformed (1).
- Gradle facts for later rules: catalog bundles, `create("libs") { from(files(...)) }` counted as a custom
  catalog, and included builds (`build-logic`) and the root counted as modules.

### Second real project: AntennaPod

`AntennaPod/AntennaPod` at `c45496d` (1,281 files: 614 Java, 14 Kotlin, 425 XML, 118 layouts; Groovy Gradle with a
version catalog; 37 modules; 11 manifests; no Compose, no navigation graph). Chosen because it is nearly the
opposite of `nowinandroid`: Java-heavy, Groovy DSL, XML views, Play Services. Read-only clone, byte-for-byte
unchanged afterwards; fault injection used a copy.

| Check | First run | After fixes |
|---|---|---|
| Findings | **20** (19 blocking): 18 false positives, 1 genuine duplicate import (warning), 1 inherited-nested-type case | **2** (the genuine duplicate import and the documented limitation) |
| Parsed facts | 37 modules, 37 namespaces from Gradle, 68 catalog libraries, 280 dependencies, 11 manifests with launcher, permissions and components | unchanged |
| Faults injected into real Java/XML that 4a should catch (missing project and library import, typo import, missing brace, unterminated string, `R.string` typo in Java, `@string` typo in a layout, duplicate class, duplicate string, unclosed layout tag) | not run | 10 of 10 |
| Faults outside 4a (manifest permission and ghost activity, nonexistent catalog alias and module, nonexistent method, type mismatch) | not run | 0 of 6, as expected (4b or a compiler's job) |
| CRLF copy of the whole project | not run | identical findings; a patch review of a CRLF file with an LF edit works |
| Patch review (removed import, benign comment) | not run | blocked / applicable; workspace byte-identical afterwards |

The false positives and their fixes (tests in `tests/test_review_realworld_java.py`, each with a twin that proves
the genuine error is still reported):

- `resValue "string", "app_name", ...` in Gradle defines a resource (6 findings); declaring it per build type is
  not a duplicate.
- Library resources with no telltale prefix (7): `appbar_scrolling_view_behavior`,
  `google_play_services_version`, `recycler_view`, `select_dialog_listview`. A small `(type, name)` table is
  trusted **only when the project declares the providing Maven group**.
- `<attr name="x"/>` without a format inside `<declare-styleable>` is a reference, not a second definition (2).
- Tool XML with a DOCTYPE outside `res/` and the manifest, such as `checkstyle.xml` (2), is not a project syntax
  error; it stays listed in `files_unparsed`. Inside `res/` or the manifest it is still reported.
- Enum constants read as uses of a library type (1): `enum ViewType { Section, Header }`.

`nowinandroid` was re-run after these fixes and still reports 0 findings.

Patch-engine hardening (commit `5aea805`). Found by reading the branches the tests did not reach (the `editing`
package was at 95% line coverage) and reproducing each one. The regression tests were written first:
`tests/test_editing_hardening.py` has 16 tests and 11 of them failed on the old code. The other 5 guard behaviour
that was already correct.

1. **The `[REDACTED]` guard could be bypassed.** It compared the text an edit *inserts* with the old file, so a
   patch could add a marker to a file that already contained one, or multiply one with `replace_all`. It now
   compares the *resulting* file with the original. (A patch can still swap one marker for another, because the
   count does not change.)
2. **One bad journal record aborted crash recovery for every patch.** `recover()` runs at worker start-up, so a
   single corrupt manifest, missing pre-image or unreadable path could stop the worker from starting. Each patch
   is now recovered on its own and a damaged one is reported under `needs_attention`; the rest are still
   recovered. `rollback()` now reports a path it cannot inspect as a `RollbackConflict` instead of a raw error.
   New `Journal.scan()` returns readable manifests and the unreadable ones separately.
3. **`journal.json` holding valid JSON that is not an object** (`[]`, `null`, `123`) crashed with
   `AttributeError`. It now raises `JournalError`.

### Platform coverage (Windows and Linux together)

Some tests can only run on one operating system, so each platform skips some. Together they cover all 415 tests:

| Test | Windows | Linux |
|---|---|---|
| 2 POSIX permission-bit tests (executable bit kept, e.g. `gradlew`) | skipped (no execute bit) | **passed** |
| 1 POSIX-only file-name test (names NTFS cannot create) | skipped | **passed** |
| 2 plain-symlink tests (symlink in the workspace is rejected) | skipped (this account cannot create symlinks) | **passed** |
| 1 NTFS-junction test | **passed** | skipped (Windows-only) |
| the other 409 tests | passed | passed |

The equivalent NTFS **junction** escape tests also ran on Windows, so the containment check is exercised on both.
The Linux run used an exported copy of the commit inside the WSL ext4 filesystem (real symlinks and permission
bits; running from `/mnt/c` would make those tests unreliable). That also covered the POSIX code paths and the
`fcntl`-based locking inside `filelock`, and Git's different timestamp handling, which is where the `pending_changes`
bug above lived. It was run once, by hand, with one Python and one git version.

**Still not run in CI.** `.github/workflows/ci.yml` does not install or test codegen (see "Needs action from other
owners"), so nothing re-runs these checks automatically on push.

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

- **Validated on two real projects** (`nowinandroid` and `AntennaPod`, see Verification): 0 and 2 findings (one
  genuine, one documented limitation), 9 of 9 and 10 of 10 injected 4a faults caught. Two projects are not a
  false-positive rate. The first runs produced 34 and 20 findings from 7 and 5 distinct patterns, and the second
  project's patterns were mostly different from the first's, so a third project will probably have more. Still
  untried: Dagger/Hilt-heavy and data-binding code, multi-flavor projects, Groovy `settings` with `projectDir`
  overrides, Kotlin Multiplatform. Run more before trusting a blocking finding in production.
- **Known false positive, left reported on purpose:** a nested type inherited from a library superclass
  (`class Bin extends NanoHTTPD { Response serve(...) }`, where `Response` is `NanoHTTPD.Response`) is reported
  as a missing import, because library classes are invisible to a static review. Excusing names inside classes
  that extend library types would also hide a missing `Context` import in every `Fragment`, which is far more
  common. A strict-xfail test records it; it fails loudly if the behaviour ever changes.
- The library-resource table (`LIBRARY_RESOURCE_NAMES`, 4 entries) is curated by hand and each entry is only
  trusted when its Maven group is declared. Other library-provided resources without a known prefix are still
  reported as unresolved.
- Heuristics added for real code are deliberately narrow: implicit-receiver calls are only excused for
  `setContent` inside `apply`/`run`/`with`; a package counts as library-provided only under framework roots, the
  curated library list or a declared dependency's group; `include(...)` paths are assumed to be directories
  (a `projectDir` override is not followed).
- `review_patch` reloads and re-parses the whole project on every call (about 4.8 s on the 715-file
  `nowinandroid`, 6.6 to 6.9 s on the 1,281-file AntennaPod; most of that is reading files), so a repair loop
  that reviews many patches should not call it in a tight loop until the "before" analysis is cached.
  Outstanding, not started.
- Inter-module dependencies (`project(":x")`, `projects.x.y`, 103 of 250 dependency lines in `nowinandroid`) are
  not modelled, only catalog and string coordinates.
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
- **Only three rule groups run** (`syntax`, `imports`, `resources`; 12 rule ids). The analysis layer already parses
  the manifest (package, permissions, components, launcher), Gradle scripts and the version catalog, and resolves
  dependency aliases, but **no rule uses that data yet**: nothing checks the manifest, navigation, dependencies,
  permissions or security. `rules/changes.py` is a placeholder that returns nothing, so there is no "this patch
  removed a component / permission / dependency" check. There is no language or framework detector.
- A review report with no findings therefore says nothing about the manifest, permissions, dependencies or
  navigation. It must not be presented as "the project is safe".

## Unfinished integration work

Not done, and not part of 4a:

- **Phase 4b** (manifest, navigation, dependency/Gradle, security, API-use, null-safety and change-aware rules).
- **More real-project validation** (see Phase 4 limitations): two projects are done, more are needed before any
  finding is allowed to block a patch in production.
- **Review is not wired to checkpoints.** `review_patch` works on a `PatchEngine`; running a review against a
  `CheckpointManager` checkpoint is not implemented.
- **No worker integration.** `workers/ai-agent` does not import `androai_codegen`; nothing consumes `CodingTask`,
  and `ReviewReport` is not mapped to the contract's `ReviewFinding` (the field names already match).
- **Contracts** are still a proposal awaiting Persons 2 and 4. **CI** does not install or test codegen, and the
  ai-agent image has no codegen package or git (details below).
- **Push**: `p3/review-engine` is on `origin` (an earlier HTTP 403 for `vinayaksahajanand-cell` no longer
  occurs). No pull request is open and `p3/codegen-foundation` has not been pushed.

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
