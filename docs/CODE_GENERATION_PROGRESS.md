# Code Generation Progress (Person 3)

Scope: `packages/agent-core/codegen` (library, `androai_codegen`) and `workers/ai-agent` (Celery adapter).

| Phase | Scope | State |
|---|---|---|
| 0 | Package setup, dev environment, this document | Done |
| 1 | File-editing abstraction and patch engine | **Done, hardened (`5aea805`), verified on Windows and Linux (WSL); not yet in CI** (see Verification) |
| 2 | Git checkpoints, manual vs AI change tracking | **Done, verified on Windows and Linux (WSL); not yet in CI** (see Verification) |
| 3 | Contracts proposal for `CodingTask` / `CodingResult` | **Drafted, awaiting Persons 2 and 4**: [CODEGEN_CONTRACT_PROPOSAL.md](CODEGEN_CONTRACT_PROPOSAL.md). No contracts PR until both approve. |
| 4 | Code review engine | **In progress. 4a done** (syntax, imports, duplicates, resources, patch review), verified on Windows and Linux (WSL) against synthetic fixtures and, on Windows, three real projects (`nowinandroid`: 0 findings, 9 of 9 injected faults caught; `AntennaPod`, Java/Groovy: 2 findings, 10 of 10; `iosched`, Hilt/Data Binding: 0 findings, 10 of 10). Phase 4a.5 added Gradle project-dependency modelling and a faster `ReviewSession`. **4b-1 done**: manifest, Gradle/dependency and change-aware rules plus review against a checkpoint (23 new rule ids; verified on Windows and Linux; 57 of 57 mutations caught; 38 of 43 faults injected into five real projects caught, the other 5 silent on purpose). Phase 4a.6 then fixed two false positives of the older rules that 4b-1's validation turned up (library-shipped resources, a class imported next to an icon property), and Phase 4a.7 the last two (`items(count = n)` and framework classes behind a wildcard import). **4b-2a done** (navigation graphs and deep links: 12 new rule ids, 59 tests, 114 of 114 mutations caught, 49 of 55 injected faults caught on five real projects, nothing reported on them unfaulted). **4b-2b done** (security: 13 new rule ids, 96 tests, 143 of 143 mutations caught; five real projects report one unconfirmed finding unfaulted, and 22 of 33 security faults injected into them are caught, the other 11 silent for reasons that were checked: mostly a target SDK that is not written as a number). **4b-2c (authentication) and 4b-3 (API use, null safety) not started**. |
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

### Phase 4b-1: manifest, build and change-aware rules

One principle runs through every rule below: **never claim what the build does not make readable.** A "X is
not declared" finding is only made when X would have been seen. A convention plugin, a dependency call that
cannot be parsed (`files(...)`, a loop variable), an unresolved catalog alias, an `allprojects { }` block or a
`project(...)` that settings does not include each make the dependent rules silent for that module. This is
why the rules produced no false positive on five real projects (see below), and it costs recall.

| Rule id | Severity | Reports |
|---|---|---|
| `manifest.class_missing` | error | a declared component, application class or alias target that does not exist in the app's own packages. Fully qualified library classes, `${placeholder}` names and `tools:node="remove\|replace"` are skipped |
| `manifest.component_undeclared` | error | an Activity / Service / Receiver (found by inheritance, abstract and test classes excluded) started with `Intent(ctx, X::class.java)` that no manifest declares |
| `manifest.exported_missing` | error | an intent filter without `android:exported`; only when `targetSdk` >= 31 is a literal number |
| `manifest.duplicate_component` | error | the same component declared twice in one manifest |
| `manifest.permission_missing` | error | network, location, camera or audio API use without the permission. Only when every module's dependencies are readable, and never when a dependency from a group that may bring `INTERNET` (Firebase, Play services, ...) is present |
| `manifest.no_launcher` | warning | an application module whose activities include no `MAIN` action |
| `gradle.unknown_catalog_alias` | error | `libs.x.y` (library, plugin, version or bundle) that `libs.versions.toml` does not define, with a "did you mean" hint. Skipped with several or custom catalogs |
| `gradle.dependency_missing` | error | an import from one of 19 well-known libraries (`LIB_DEPENDENCIES`) that no dependency of the module, or of the modules it depends on, provides. Compose is deliberately absent because it arrives transitively |
| `gradle.compose_plugin_missing` | error | `buildFeatures { compose = true }` with a literal Kotlin version >= 2.0 and no `org.jetbrains.kotlin.plugin.compose` plugin |
| `gradle.sdk_order` | warning | `minSdk > targetSdk` or `targetSdk > compileSdk` (literals in one script) |
| `gradle.duplicate_dependency`, `gradle.conflicting_versions` | warning | the same coordinate twice in one configuration, with or without differing versions |
| `gradle.unplanned_dependency` | error, approval `other_high_impact` | with `ReviewConfig.permitted_dependencies` set, any library outside the plan (entries: group, `group:artifact`, `group:*`) |
| `change.component_removed`, `change.permission_removed`, `change.dependency_removed` | warning | something the project had before is gone. A component matches under any spelling of its class (relative or fully qualified), so a package rename is one finding. A dependency is "removed" only if its coordinate is declared nowhere in the project afterwards |
| `change.integration_removed` | error, approval `remove_integration` | a payment or authentication dependency (`SENSITIVE_DEPENDENCY_GROUPS`) disappeared |
| `change.package_renamed` | error, approval `rename_package` | `applicationId`, `namespace` or the manifest `package` changed |
| `change.language_converted` | error, approval `convert_language` | a `.java` file replaced by a `.kt` file of the same name, or the reverse |
| `change.ui_toolkit_converted` | error, approval `convert_ui_toolkit` | a file that built its screen from XML layouts now uses Compose, or the reverse (judged per file, and only if it stopped using the old toolkit) |
| `change.tests_removed` | warning | fewer `@Test` methods in total than before (moving a test between files is not reported) |
| `change.sdk_changed` | warning | `minSdk` raised, or `targetSdk` / `compileSdk` lowered |
| `change.component_exported` | warning | a component without an intent filter became exported |

Findings that carry an `approval` are downgraded to non-blocking info ("(approved)") when `ReviewConfig.granted_approvals`
contains that kind, exactly as in the proposed contract. The change-aware rules only run when a "before" state
exists (a patch review or a checkpoint review) and only look at files that differ between the two states.

**Review against a checkpoint** (new): `review_since_checkpoint(manager, checkpoint_id)` takes the project as it is
now, rebuilds it as it was at the checkpoint from the shadow-git history (only the files that differ are read
back) and reports what changed since, including edits nobody recorded yet. `project_at_checkpoint` exposes the
rebuilt project. Nothing is written to the workspace or the history.

### Phase 4b-2a: navigation and deep links

The behaviour below was checked against the official Android documentation before any rule was written
(developer.android.com: Navigation design and deep links, `NavController`, `NavGraph`, "Create deep links" and
"Verify Android App Links"). Navigation 3 (`NavDisplay`, `NavKey`) is a different library and is **out of scope**:
a project that imports `androidx.navigation3` is not judged by the Compose rules, and nothing computed is guessed.

| Rule id | Severity | Reports | Documented basis |
|---|---|---|---|
| `navigation.destination_missing` | error | `navigate("route")` or `navigate(RouteType(...))` where no `composable` / `dialog` / `navigation` of the project declares it. `{arg}` segments match filled-in and `$template` calls; the query string is ignored | `navigate` "throws `IllegalArgumentException`" for an invalid route |
| `navigation.start_destination_missing` | error | a `NavHost` or `navigation(...)` start destination nothing declares; an XML `<navigation>` with destinations but no `app:startDestination`, or one pointing at an id that is not its own | a graph "is not valid until you add destinations and set a start destination" |
| `navigation.action_target_missing` | error | an XML `<action app:destination="@id/x">` where no navigation graph in the project declares `x` | same |
| `navigation.destination_class_missing` | error | an XML `<fragment>` / `<activity>` / `<dialog>` naming a fully qualified class of the app's own packages that does not exist | |
| `navigation.duplicate_destination` | warning | one route declared twice in one graph builder (same function), or one `android:id` twice in one XML graph | not documented by Android, so worded as "ambiguous", not as a crash |
| `deeplink.missing_browsable` | warning | a VIEW filter for `http`/`https` without `BROWSABLE` | "required in order for the intent filter to be accessible from a web browser" |
| `deeplink.missing_default` | warning | a VIEW filter with `<data>` but no `DEFAULT` | "the activity can be started only if the intent specifies your app component name" |
| `deeplink.autoverify_ineffective` | warning | `autoVerify="true"` on a filter lacking VIEW, BROWSABLE, DEFAULT or an http/https scheme, or mixing in another scheme | "do not include other schemes, as this will prevent verification" |
| `deeplink.merged_data_elements` | warning | `<data>` elements of one filter that differ in both scheme and host (the cross product also matches unintended URIs) | the guide's own `https://www.example.com` plus `app://open.my.app` example |
| `deeplink.duplicate_app_link` | warning | the same verified link in two different components | "no guarantee as to which Activity handles the link" |
| `deeplink.nav_graph_not_in_manifest` | warning | an XML graph with `<deepLink>` that no `<nav-graph>` in any manifest enables (and no other graph includes) | XML graphs "must also add a single `<nav-graph>` element" |
| `deeplink.uri_not_in_manifest` | warning | a Compose `navDeepLink { uriPattern = "..." }` / `navDeepLink<T>(basePath = "...")` literal whose scheme and host no manifest VIEW filter matches (wildcard hosts, a missing scheme meaning http or https, and host-less filters are honoured) | programmatic graphs "cannot automatically generate" the manifest filters |

All deep-link findings are warnings, because a link may be meant to be reachable only from inside the app.

### Phase 4b-2b: security

The behaviour below was checked against developer.android.com before any rule was written: the `PendingIntent`
reference (`FLAG_IMMUTABLE`, `FLAG_MUTABLE`, `FLAG_NO_CREATE`, `FLAG_ALLOW_UNSAFE_IMPLICIT_INTENT`), the Android 12 and
14 behaviour changes, the `<provider>`, `<grant-uri-permission>` and `<application>` manifest references, the network
security configuration guide, the security tips, and the `android.Manifest.permission` reference (for the protection
level of every permission in the catalog; a test pins the two permission tables to it). Lint issue ids were taken from
the Android lint check documentation. Nothing here claims to verify an app's authorization model; these are
manifest, build and call-site checks that stay silent when they cannot read what they need.

| Rule id | Severity | Reports | Documented basis |
|---|---|---|---|
| `security.pending_intent_mutability` | error | `PendingIntent.getActivity/getActivities/getBroadcast/getService/getForegroundService` whose flags are readable (`PendingIntent.FLAG_*` constants, `or` / `\|`, or `0`) and name neither `FLAG_IMMUTABLE` nor `FLAG_MUTABLE`, where the app targets 31+. A `FLAG_NO_CREATE` lookup is not a creation and is not judged | "Starting with S, it will be required to explicitly specify the mutability of PendingIntents on creation" |
| `security.pending_intent_mutable_implicit` | error | `FLAG_MUTABLE` around an inline implicit `Intent("action")` / `Intent()` / `Intent(Intent.ACTION_X)`, target 34+, without `FLAG_ALLOW_UNSAFE_IMPLICIT_INTENT` | "creation of a PendingIntent with FLAG_MUTABLE and an implicit Intent within will throw an IllegalArgumentException" for apps targeting U |
| `security.receiver_export_flag_missing` | error | `registerReceiver(receiver, IntentFilter("custom.action"))` (the 2- and 4-argument forms) where the inline filter's actions are all readable and at least one is not a system (`android.`) action, target 34+ | the Android 14 behaviour change (context-registered receivers must say `RECEIVER_EXPORTED` or `RECEIVER_NOT_EXPORTED` unless they register only for system broadcasts), and lint `UnspecifiedRegisterReceiverFlag`: "In Android U, all receivers registering for non-system broadcasts are required to include a flag indicating the receiver's exported state" |
| `security.provider_exported_unprotected` | warning | `<provider android:exported="true">` with no `permission` / `readPermission` / `writePermission` and no `<path-permission>`; says so when it can also grant URI permissions | security tips: export only what other apps must reach and protect it with a permission; lint `ExportedContentProvider` |
| `security.provider_grants_all` | warning | `<grant-uri-permission>` with `pathPrefix="/"` or `pathPattern` `.*` / `/.*` | the element's reference: a prefix matches "all data subsets with paths that share that initial part", `.*` matches "any sequence of zero to many characters"; lint `GrantAllUris` |
| `security.service_exported_unprotected` | warning | `<service android:exported="true">` with no `android:permission` whose intent-filter actions, if any, are all custom | lint `ExportedService` |
| `security.receiver_exported_unprotected` | warning | the same for `<receiver>` | lint `ExportedReceiver` |
| `security.cleartext_enabled` | warning | `android:usesCleartextTraffic="true"` in a `main` manifest with no `networkSecurityConfig` (the attribute is ignored on API 24+ when a config exists). Notes the platform default only when the target is known to be 28+ | the attribute's reference: default true up to API 27, false from API 28 |
| `security.cleartext_permitted` | warning | a network security config whose `base-config`, or `domain-config` for a real (not local-development) domain, sets `cleartextTrafficPermitted="true"` | "cleartext traffic ... should be avoided whenever possible"; lint `InsecureBaseConfiguration` |
| `security.cleartext_url_blocked` | warning | a literal `http://` URL given to `baseUrl(...)`, `url(...)` or `URL(...)` for a non-local host, where the app targets 28+ and *nothing* in the project's manifests or network security config permits cleartext | the default of `usesCleartextTraffic` from API 28 |
| `security.permission_not_declared` | warning | a dangerous permission named in a file that requests or checks run-time permissions, while no manifest in the project declares it | the runtime permission workflow (declare, then request) |
| `security.permission_never_requested` | warning | a dangerous permission declared in a `main` manifest, mentioned nowhere in the project, in a module whose own code requests or checks other permissions | same |
| `change.sensitive_permission_added` | error, `approval="other_high_impact"` | a dangerous or special-access permission the project did not declare before. Judged across the whole project, so moving it between manifests is not an addition; skipped when the "before" project has no manifest | the reference's protection levels: `dangerous`, or `appop` / installer-granted special access |

**How a finding is judged.**

- *Premises are checked, not assumed.* The `PendingIntent`, receiver and URL rules need the app's target SDK as a
  literal (a library module is judged by the lowest target of the applications of the build; an unreadable one makes
  it silent), and the URL rule additionally needs every shipping manifest parsed, no `usesCleartextTraffic` other than
  `false`, and any network security config readable and not permitting cleartext at all (even for localhost).
- *Unreadable means silent.* Flags held in a variable or computed, an intent built elsewhere (or with `setPackage`),
  a filter held in a field, an `addAction` with a constant of our own, a template URL, `LocalBroadcastManager` (no
  export flag exists for it), a `registerReceiver` of a shape the platform does not have: none is judged. Comments
  inside the flags neither hide nor add a flag.
- *Local development hosts are not reported* (`localhost`, loopback, private ranges, `.local`/`.test` names,
  documentation placeholders, dotless names).
- *Suppressions the project already made are honoured*, for the rules that have a documented lint id: `tools:ignore`
  on the element or an enclosing one (or `all`), `@SuppressLint` / `@Suppress` / `@SuppressWarnings` / `@file:Suppress`
  anywhere in the file, an unrestricted `lint.xml` entry with severity `ignore`, and an id named after `disable` /
  `ignore` in a Gradle script. This errs towards silence. No suppression is honoured for a rule without a documented
  id (`cleartext_enabled`, `cleartext_url_blocked`, the permission rules), and `tools:ignore` on a `domain-config` is
  not honoured.
- *Keys survive edits.* Call-site findings are keyed by their call (kind and flags, actions, or URL) plus an ordinal
  among identical calls, so a second identical call added by a patch is new rather than hidden, and an unrelated
  edit does not make an old finding new.

Reuses the existing approval kind `other_high_impact`; no new contract kind is introduced.

**Not implemented yet (4b-2c and 4b-3):** authentication (recognised sign-in integrations, redirect configuration,
hardcoded secrets, plain-text token storage), incorrect API use and null safety.

## Generation workflow, supported technologies, repair rules

**Not implemented yet** (Phases 5-8). Planned per the Role 3 spec: Kotlin first with Jetpack Compose, then
Java and XML layouts, and a repair loop bounded by iteration, time, cost, repeated-error and no-progress
limits, returning infrastructure and provider failures to orchestration without touching source.
The patch engine is language-agnostic: it edits UTF-8 text files and knows nothing about Kotlin or Gradle.

## Verification

Results below are for `p3/review-engine` (Phase 4a, the patch-engine hardening, the real-project fixes, 4b-1, 4b-2a and 4b-2b).

| Platform | Commit | `pytest packages/agent-core/codegen` | Ruff |
|---|---|---|---|
| Windows 10, Python 3.12.10, Git 2.56.1 | Phase 4b-2b (the commit that added this row) | **778 passed, 5 skipped, 1 xfailed** (about 2.4 min) | `ruff check` clean; `ruff format --check` clean (74 files); `compileall` clean |
| Linux (WSL Ubuntu, Python 3.14.4, git 2.53.0, ext4), working-tree export | Phase 4b-2b | **782 passed, 1 skipped, 1 xfailed** (about 32 s) | `ruff check` clean; `ruff format --check` clean (Linux ruff counted 75 files; both trees hold the same 74 `.py` files); `compileall` clean |
| Windows / Linux | `65e9d50` (Phase 4b-2a) | 682 passed, 5 skipped, 1 xfailed / 686 passed, 1 skipped, 1 xfailed | clean (72 files) |
| Windows / Linux | `912727b` (Phase 4a.7) | 623 passed, 5 skipped, 1 xfailed / 627 passed, 1 skipped, 1 xfailed | clean (67 files) |
| Windows / Linux | `b12e5b8` (Phase 4a.6) | 594 passed, 5 skipped, 1 xfailed / 598 passed, 1 skipped, 1 xfailed | clean (66 files) |
| Windows / Linux | `12c2618` (Phase 4b-1) | 576 passed, 5 skipped, 1 xfailed / 580 passed, 1 skipped, 1 xfailed | clean (64 files). Measured one edit before the commit: a pure performance memoization of `dependency_groups_for`, re-checked by the review tests |
| Windows 10, Python 3.12.10, Git 2.56.1 | `8f20e01` (code of the latest commit) | **500 passed, 5 skipped, 1 xfailed** (about 1.3 min: the VCS tests spawn git) | `ruff check` clean; `ruff format --check` clean (58 files); `compileall` clean |
| Linux (WSL Ubuntu, kernel 6.18 WSL2, Python 3.14.4, git 2.53.0, ext4), `git archive` export | `8f20e01` | **504 passed, 1 skipped, 1 xfailed** (about 24 s) | `ruff check` clean; `ruff format --check` clean (58 files); `compileall` clean |
| Windows / Linux | `ce547ad` | 454 passed, 5 skipped, 1 xfailed / 458 passed, 1 skipped, 1 xfailed | clean (53 files) |
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

### Phase 4a.5: project dependencies and a faster patch review

**Gradle project dependencies** (`019f3df`). `project(":a:b")` (also Groovy `project(path: ':a:b')`,
`project(':a', 'cfg')` and `testFixtures(project(...))`) and typesafe accessors `projects.a.b` (kebab-case
`data-test` -> `dataTest`, nested) are resolved against the root `settings` includes into module directories
(`ProjectAnalysis.project_dependencies`, `module_graph`). New rule `gradle.unknown_project` reports a dependency
on a project that settings does not include, with a "did you mean". It only speaks when the project list is
readable: not when settings is missing, has no includes, includes dynamically (`include(it)`) or remaps a
`projectDir`; scripts of included builds and `buildSrc` are not checked against the main settings. Coverage was
checked against an independent grep: `nowinandroid` 101 of 101 references resolved, AntennaPod 176 of 176.
Catalog and string dependencies behave as before. Dependencies written as `buildSrc` constants
(`implementation(Libs.MATERIAL)`, nested objects included) resolve to coordinates too (added for `iosched`).

**`ReviewSession`** (`bf4c43a`). `review_patch` used to read every file and analyse the unchanged project for
every patch. A session caches file texts by size and mtime (a file modified in the last 2 s is always re-read,
like git's racily-clean rule), reuses the "before" analysis only while the project text is identical, keeps
nothing from a patch, and is bound to one workspace, project id, config and target (`ValueError` otherwise).
`review_patch(..., session=...)` uses it; without a session nothing changed. Measured on the same machine, 6
sequential patch reviews, results identical to the stateless path:

| Project | Stateless, per review | Session, first review | Session, later reviews |
|---|---|---|---|
| `nowinandroid` (715 files) | 4.8 to 5.3 s | 4.9 to 5.1 s | **2.5 to 2.6 s** |
| `AntennaPod` (1,281 files) | 6.4 to 7.3 s | 6.5 to 6.7 s | **3.3 to 3.4 s** |
| `iosched` (942 files) | 5.3 to 6.1 s | 5.4 s | **2.8 s** |

About 2x. What remains is analysing the patched project (about 1.4 s) and the walk + stat that detects changes.
Known blind spot: an edit that keeps size and mtime and is older than 2 s (`touch -r`).

### Third real project: iosched (Hilt, Data Binding, buildSrc)

`google/iosched` at `738e1e008096fad5f36612325275e80c33dbe436` (942 files: 419 Kotlin, 433 XML with 69 layouts, 48 of
them Data Binding `<layout>`; Hilt; 9 modules; 9 manifests; dependencies as `buildSrc` constants, no version
catalog, no Java). Read-only clone, byte-for-byte unchanged; fault injection used a copy.

| Check | First run | After fixes |
|---|---|---|
| Findings | **15** blocking, all false positives | **0** |
| Faults injected into real Kotlin/XML that 4a should catch (missing project and library import, typo import, missing brace, unterminated string, `R.string` and `@string` typos, duplicate class, duplicate string, unclosed layout tag) | not run | 10 of 10 |
| Hilt/Dagger probes (removed `@AndroidEntryPoint` / `@Inject` import) | not run | 2 of 2 |
| Data Binding probes | not run | `@{@string/missing}` caught; `<variable type="...Missing"/>` **not caught** (unsupported) |
| Faults outside 4a (manifest permission, ghost activity, nonexistent buildSrc constant) | not run | 0 of 3, as expected; a nonexistent module is caught by the new rule |
| CRLF copy | not run | identical findings |

The 15 false positives and their fixes (`tests/test_review_realworld_hilt.py`, each with a twin):

- Extension properties with a generic or star-projected receiver (`val Result<*>.succeeded`) were not
  declarations (2).
- A project function and a class of the same name imported together (`fun Rule.CoroutineScope()` and
  `kotlinx.coroutines.CoroutineScope`), and same-named lowercase Kotlin imports (overloads), were reported as
  conflicts (1). Two types of one name still conflict.
- `dataStore.edit {}` demanded the SharedPreferences `edit` import although DataStore's own `edit` was
  imported; any import of the name now satisfies the call (1).
- Hilt output in class literals (`CustomTestRunner_Application::class`) is generated (1).
- Dependencies declared as `buildSrc` constants hid the dependency that makes a library resource legitimate
  (10 findings): `appbar_scrolling_view_behavior`, `google_play_services_version` and the fragment-testing theme.
- `buildSrc` was counted as a module.

`nowinandroid` (0) and AntennaPod (2) were re-run and are unchanged.

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

### Phase 4b-1 verification

- **76 new tests** (manifest 30, Gradle 20, change-aware 20, checkpoint 6). The known-good sample project still
  reports nothing under any of the 23 new rules, and none of the 500 earlier tests changed except one fixture
  (an old test imported DataStore into an app that does not depend on it, which the new rule correctly reported;
  the fixture now declares the dependency).
- **Mutation check: 57 of 57 caught.** Each mutation breaks one piece of a rule (a guard, an exclusion, a
  severity, an approval kind) and must make a test fail. The first run caught 49 of 56; the survivors were real:
  missing tests for a double report on an alias, a class literal outside an `Intent`, `libs.findLibrary`, an
  unresolved plugin alias, an unresolved project dependency and a component that was already exported, and one
  **real design flaw**: components were identified relative to the package, which made a fully qualified name
  look "removed" when only the package changed. Components now match under any spelling of their class.
- **Real projects, no injected faults (5 clones):** the manifest, `dependency_missing` and catalog rules reported
  nothing. `nowinandroid`, `iosched` and `sunflower` have no module whose dependency list is fully readable
  (convention plugins, constants), so the rules that need one are silent there by design. The only new findings
  were three `gradle.duplicate_dependency` warnings, all **true**: `iosched` declares `ARCH_TESTING` twice in
  `shared`, and two constants for the same `compose-theme-adapter` coordinate in `mobile`; one `p2` module declares
  `lifecycle-runtime-ktx` twice.
- **Real projects, faults injected in memory (43 faults, 5 projects): 38 caught, 5 silent.** Caught: renamed or
  ghost component, undeclared activity started through an `Intent`, catalog typo, library imported without its
  dependency (in readable modules), changed `applicationId`, deleted test file, Java file converted to Kotlin,
  permission removed. Silent, each for a known reason: `android:exported` dropped (3 projects whose `targetSdk`
  is a constant, not a literal) and one dependency line deleted (2 projects where the same library is declared in
  other modules too). In all five projects the missing-INTERNET fault was caught only by `change.permission_removed`:
  `manifest.permission_missing` stayed silent because some module's dependencies are not fully readable.

### Phase 4a.6: two false positives found on real projects

Both appeared when 4b-1 was validated on `android/platform-samples` (the older 4a rules, not the new ones).

1. **`import.conflicting` for a class next to an icon.** `import android.provider.Settings` together with
   `import androidx.compose.material.icons.rounded.Settings` was reported as two imports of one name. Kotlin only
   rejects an import clash between two *classifiers*; the icon is an extension property, so it never clashes with
   anything. The old check excused two icons but not an icon next to a class. It now excuses any pair in which
   either side is a known icon. Two classes of one name (`java.util.Date` and `java.sql.Date`, in Kotlin and in
   Java) are still reported, including when an unrelated icon is imported in the same file.
2. **`resource.unresolved` for resources a library ships.** `@layout/glance_default_loading_layout`,
   `@bool/glance_appwidget_available` (Glance), `@color/cardview_shadow_start_color` (CardView) and
   `@animator/nav_default_*_anim` (Navigation) were reported (17 findings in one project), because a project cannot
   see inside a library. The curated table only knew exact names. It now also knows a library's name *families*
   (`LIBRARY_RESOURCE_FAMILIES`: `glance_*`, `cardview_*` (CardView or Material Components), `nav_default_*`
   (animations only) and `lb_*` (Leanback)), trusted the same way as before: only when the project declares a
   library of that group. The same name without the library is still reported, and a name with the right prefix but
   the wrong resource type (a *string* called `nav_default_enter_anim`) is not excused.

**An attempt that was reverted.** A first version also excused these names whenever the module's dependencies
could not be read in full. An existing test (`test_library_resource_is_still_unresolved_without_the_providing_dependency`)
deliberately asserts the opposite, and the real project did not need it (it declares the libraries), so the fallback
was removed and the existing behaviour kept. The consequence is the limitation already listed: a library that only
a convention plugin adds is not seen, and its resources are still reported.

Results: `platform-samples` 17 `resource.unresolved` and 1 `import.conflicting` to 0 and 0; no other change on any
of the five projects. 18 new tests (6 for imports, 12 for resources), 7 new mutations, all caught; the original 22
4a mutations are still all caught (two of their anchors had gone stale in an earlier refactor, before this work, and
were refreshed).

### Phase 4a.7: two `import.missing` false positives found on real projects

1. **`items(count = n)` in a lazy list or grid** (sunflower, `GalleryScreen.kt`). `LazyListScope` and
   `LazyGridScope` declare `items(count: Int, ...)` themselves, so that form needs no import; only the extension
   that takes a list (`...lazy.items`, `...lazy.grid.items`) does. A catalog pattern can now carry a
   `member_form`: a call shape that only the member can have. For `items` it is a first argument that is certainly
   an `Int`: a named `count =`, an integer literal, or an expression ending in `.size` or `.itemCount`. The list
   form (`items(list)`, `items(items = list)`) is still reported without its import, also when a member call is
   present in the same file. `items(total)` is **not** excused: `total` may be an `Int` or a list and nothing in
   the call says which (a test pins this as a documented limit).
2. **Framework classes behind a wildcard import** (platform-samples, `Surface` with `import android.view.*`). The
   catalog listed `Surface` only as the Compose type, so no wildcard import could ever provide it. A probe of the
   catalog found the same gap for seven more names that exist both as Compose or library types and as framework
   classes: `Color` and `Canvas` (`android.graphics`), `Path` (`android.graphics`, listed after Retrofit's so the
   annotation stays the first suggestion), `Icon` (`android.graphics.drawable`), `Image` (`android.media`),
   `RadioButton` (`android.widget`) and `Snackbar` (Material Components). All eight are now listed. An explicit
   import of any of them already worked; a wildcard of an unrelated package still does not provide them, and the
   same names with no import at all are still reported.

Results: `sunflower` 1 `import.missing` to 0, `platform-samples` 1 to 0; no other change on the five projects (what is left
is a documented xfail, a true duplicate import and three true duplicate-dependency warnings). 29 new tests (10 for
`items`, 19 for the framework classes, including Java and the suggestion order), 13 new mutations: all 77 current
mutations are caught, and the original 22 4a mutations still are.

### Phase 4b-2a verification

- **59 new tests** (navigation 35, deep links 24). The known-good sample project, which has a real `NavHost`,
  still reports nothing under any new rule. The 4b-1 and 4b-2a test helpers now also assert that no
  `review.internal_error` is produced: a rule that crashes is turned into that finding, which a test filtering by
  rule prefix would mistake for silence. This closed a real blind spot (see below); the 76 older 4b tests passed
  with the assertion, so nothing was crashing unnoticed.
- **Mutation check: 114 of 114 caught** (37 new, 77 earlier), and the original 22 4a mutations still are. The first
  run caught 112 of 115. One survivor was an *equivalent* mutant (a redundant guard, removed from the code), one was
  a missing test (a navigation file without a `NavController`), and one was the crash blind spot: a mutation made a
  rule raise, the engine reported it as `review.internal_error`, and the prefix-filtered test saw "no finding".
- **Two defects found by the tests themselves, not by review:** `composable<Home> { ... }` with a trailing lambda
  has no parentheses, and the first regex required them, so every type-safe test would have passed *vacuously*;
  and the `@Serializable` check looked 300 characters back, so a class without the annotation inherited the one
  of the declaration above it. Both are fixed and covered.
- **Real projects, no faults (5): nothing reported by any 4b-2a rule.** The analysis really reads the structure
  (`iosched`: 3 XML graphs, 8 actions, 19 destination ids; `platform-samples`: 1 graph, 7 actions; `AntennaPod`: 25
  intent filters, 4 with `autoVerify`; `nowinandroid` is recognised as Navigation 3 and skipped). The Compose rules
  stayed silent on every project that has a `NavHost`: `sunflower` starts at `Screen.Home.route` (a property of a
  sealed class), `platform-samples` starts from a variable and has a non-`const` route. That is the designed
  behaviour, but it means **no real project exercised the Compose route rules**; only the tests did.
- **Real projects, faults injected in memory (55 faults over the five projects, 12 of them new): 49 caught, 6
  silent.** New and caught: an XML action to a missing destination (`iosched`, `platform-samples`), a dropped
  `app:startDestination` (both), `BROWSABLE` removed from a web filter (`nowinandroid`, `platform-samples`,
  `AntennaPod`), a custom scheme added to an `autoVerify` filter (`AntennaPod`), a `navDeepLink` for a host no
  filter matches (`iosched`, `sunflower`, `platform-samples`). The one new miss is `AntennaPod`'s `navDeepLink`,
  and it is correct: that app declares a catch-all `https` filter with no host, so a link to any host reaches it.
  The other five silent cases are the ones from 4b-1.

### Phase 4b-2b verification

- **96 new tests** (`tests/test_review_security.py`): every rule has a positive case and the twins that must stay
  quiet (the compliant form, the form the analyzer cannot read, the premise that does not hold, each boundary SDK
  level, each exemption). A test pins `DANGEROUS_PERMISSIONS` and `SPECIAL_ACCESS_PERMISSIONS` to the documented
  protection levels, and the known-good sample project still reports nothing. Test helpers assert that no
  `review.internal_error` appears.
- **Mutation check: 143 of 143 caught** (the 4b-2b rules, their fact scanner and the change rule), and the earlier
  suites still pass: 114 of 114 (4a.6 to 4b-2a) and 22 of 22 (4a). All 75 tests passed on the first run, which proves
  nothing about tests written alongside the code; the first mutation run caught 106 of 107. The survivor was a
  missing test (the lower-casing in the local-host check is only reachable through a network security config
  domain). Two later anchors went stale because the code was edited, and were re-run on their own.
- **Real projects, no faults (5): one security finding in total, and it is unconfirmed.** `AntennaPod` reports
  `security.permission_not_declared` for `READ_EXTERNAL_STORAGE` in `OpmlImportActivity` (the repository declares no
  such permission; a dependency's manifest might, and that cannot be read without a build). Nothing is reported on
  `nowinandroid`, `iosched`, `sunflower` or `platform-samples`.
  - **Two findings disappeared because the project had already acknowledged them**, which led to the suppression
    support: `AntennaPod`'s `FeedUpdateReceiver` carries `tools:ignore="ExportedReceiver"` (and the app module's Gradle
    `lint` block disables `ExportedReceiver` too), and its `base-config` carries `tools:ignore="InsecureBaseConfiguration"`. Both were true
    observations about a deliberate design, reported as news before the change.
- **The call-site rules were checked against real code with the missing premise supplied.** Because only
  `platform-samples` writes a literal `targetSdk`, the `PendingIntent`, receiver and URL rules were run once more
  with the target forced to 35 (an experiment in a throwaway process, not a behaviour): `iosched`'s two real
  `PendingIntent.getBroadcast` calls with `FLAG_UPDATE_CURRENT` and `0` are reported (correctly: they have no
  mutability flag; `iosched` targets 30, so the product stays silent), and the 16 calls of `platform-samples`, the 9
  of `AntennaPod` and the 1 of `nowinandroid` produce nothing. Two `platform-samples` calls remain unreadable because
  their flags are an `if (SDK_INT < S) ... else ...` expression, which is silence by design.
- **Three defects found by real projects, not by the tests:** (1) the project's own `tools:ignore` / `lint.xml`
  suppressions were ignored (above); (2) a comment inside the flags argument (`/* flags = */ A or B`, or a `//`
  note before the constants) made the call unreadable, because flags were read from raw text (four `platform-samples`
  calls; fixed by reading the comment-masked text, two remain for the reason above); (3) `iosched`'s `ar` module
  declares `CAMERA` and `WRITE_EXTERNAL_STORAGE`, never mentions them and relies on ARCore to ask, so
  `permission_never_requested` would have been a false positive as soon as that project's target became readable.
  The rule is now judged only in a module whose own code requests or checks permissions. Two guards that no input
  could distinguish from their absence (`ContextCompat` and a `RECEIVER_` text check) were removed rather than kept.
- **Real projects, faults injected in memory (88 faults over the five projects, 33 of them new): 71 caught, 17
  silent.** The 33 new security-scope faults: 22 caught, 11 silent. Caught: a `PendingIntent` that loses
  `FLAG_IMMUTABLE` (`platform-samples`), a mutable implicit `PendingIntent`, `registerReceiver` without an export flag
  and a plain-HTTP `baseUrl` (`platform-samples`), a request for an undeclared permission (four projects), an
  exported service, provider and receiver (all four projects with a readable app module; on `AntennaPod` the receiver
  stays silent because its Gradle lint configuration disables `ExportedReceiver`), a `grant-uri-permission` for every path,
  `usesCleartextTraffic="true"` (three projects), and a newly added `RECORD_AUDIO` (three projects). The 11 silent ones
  all have a reason that was checked: for `iosched`, `sunflower` and `AntennaPod` the `PendingIntent`, receiver and
  URL faults are silent because the target SDK is not a literal (9 faults; `AntennaPod`'s app module takes it from
  `common.gradle`), the `AntennaPod` URL fault is silent anyway because that project permits cleartext, and
  `RECORD_AUDIO` is not "added" to `platform-samples` because five of its samples already declare it (the rule is
  project-wide on purpose). `nowinandroid` has no readable application module (convention plugins), so none of the new
  faults could be injected there. The other 6 silent faults of the 88 are the ones from 4b-1.

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

- **Validated on three real projects** (`nowinandroid`, `AntennaPod`, `iosched`; see Verification): 0, 2 (one
  genuine, one documented limitation) and 0 findings, with 9 of 9, 10 of 10 and 10 of 10 injected 4a faults
  caught. Three projects are not a false-positive rate. The first runs produced 34, 20 and 15 findings from
  7, 5 and 6 distinct patterns, and each project's patterns were largely different from the others', so a
  fourth project will probably have more. Still untried: multi-flavor projects, Groovy `settings` with
  `projectDir` overrides, Kotlin Multiplatform, Java-heavy code that uses Dagger, annotation-processor output
  other than Hilt/Room/data binding. Run more before trusting a blocking finding in production.
- **Data Binding is not analysed.** `<layout>` expressions and `<variable type="...">` / `<import type="...">`
  are not checked, so a data-binding type that does not exist is not reported. Resource references inside
  expressions (`@{@string/x}`) are.
- **Dependencies are only read when they are literal.** Coordinates, catalog aliases (including bundles),
  `project(...)`/`projects.x` and `buildSrc` `const val` constants are understood. Dependencies computed in
  convention plugins, `subprojects { }` blocks or helper functions are invisible, so a library resource that
  only such a dependency provides is reported as unresolved.
- **Known false positive, left reported on purpose:** a nested type inherited from a library superclass
  (`class Bin extends NanoHTTPD { Response serve(...) }`, where `Response` is `NanoHTTPD.Response`) is reported
  as a missing import, because library classes are invisible to a static review. Excusing names inside classes
  that extend library types would also hide a missing `Context` import in every `Fragment`, which is far more
  common. A strict-xfail test records it; it fails loudly if the behaviour ever changes.
- The library-resource tables (`LIBRARY_RESOURCE_NAMES`, 4 exact names, and `LIBRARY_RESOURCE_FAMILIES`, 4 name
  families) are curated by hand and each entry is only trusted when its Maven group is declared. Other
  library-provided resources without a known prefix are still reported as unresolved, and so is a library resource
  whose library only a convention plugin adds.
- Heuristics added for real code are deliberately narrow: implicit-receiver calls are only excused for
  `setContent` inside `apply`/`run`/`with`; a package counts as library-provided only under framework roots, the
  curated library list or a declared dependency's group; `include(...)` paths are assumed to be directories
  (a `projectDir` override is not followed).
- Patch review is still about 2.5 to 3.4 s per patch with a `ReviewSession` (4.8 to 7.3 s without): analysing
  the patched project is repeated for every patch. A per-file incremental analysis is not done. Plain
  `review_patch` without a session still reloads everything on every call.
- A dependency on a project that settings does not include is reported (`gradle.unknown_project`), but nothing
  else uses the module graph yet: no cycle check, no "module X must not depend on Y", no check that a module
  uses what it depends on.
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
- **Nine rule groups run** (`syntax`, `imports`, `resources`, `gradle`, `manifest`, `navigation`, `deeplinks`,
  `security` and, with a "before" state, `changes`; 61 rule ids). Nothing checks authentication, incorrect API use or
  null safety yet (4b-2c and 4b-3), and there is no language or framework detector. The security group is the
  narrow set listed under Phase 4b-2b, not a security audit.
- A review report with no findings therefore says nothing about authentication or API use, and little about
  security. It must not be presented as "the project is safe".

Phase 4b-1 (manifest, build and change-aware rules):

- **Recall is deliberately limited by readability.** `gradle.dependency_missing` and `manifest.permission_missing`
  need a module's whole dependency list, so they are silent for any module that applies a convention plugin or
  has a dependency call that cannot be parsed. `manifest.permission_missing` further needs *every* module to be
  readable, so on real multi-module projects it usually does not fire (it was silent on all five clones).
  `manifest.exported_missing` and `gradle.compose_plugin_missing` need a literal `targetSdk` / Kotlin version, and
  a constant or a convention plugin silences them (3 of 5 clones). Readable single-module projects, which is what
  generation produces, get the full set.
- `change.dependency_removed` is judged project-wide: removing a library from one module while another module
  still declares it is not reported. Moving a dependency between modules is therefore not noise, and a real
  removal from one module can be missed.
- `gradle.dependency_missing` knows 19 libraries (`LIB_DEPENDENCIES`). Anything else, and everything in Compose,
  is not checked. It also accepts the library from any configuration, so `testImplementation` satisfies a `main`
  import.
- Permission rules cover network, location, camera and audio only, by import (and, for `LocationManager` and
  `MediaRecorder`, by call). Other dangerous permissions, runtime permission requests and `uses-permission`
  entries that are unused are not checked.
- `manifest.component_undeclared` only sees classes started through `Intent(ctx, X::class.java)` (Kotlin and Java
  literals). A component started by name, through a library, or from XML is not seen.
- `change.ui_toolkit_converted` judges one file at a time: it needs a file that stopped using `R.layout` /
  view binding and started using `setContent { }` or `@Composable` (or the reverse). A conversion spread over
  several files, or one that keeps a single XML reference, is not reported. `change.language_converted` needs the
  same file name in the same directory.
- `gradle.sdk_order` is a warning because the exact behaviour of the Android Gradle plugin for out-of-order levels
  was not verified against a build. `gradle.compose_plugin_missing` states what the Kotlin 2.0 Compose compiler
  plugin requires; it was not checked against a real failing build either. Nothing in 4b was compiled.
Phase 4b-2a (navigation and deep links):

- **The Compose route rules only engage when every route is a literal or a `const val`.** A start destination such
  as `Screen.Home.route` (a property of a sealed class), a variable, a non-`const` `val`, a `NavHost` given a prebuilt
  graph, or any `composable(route)` whose route is computed marks the project "dynamic" and silences the rules. On
  the five real projects that is what happened everywhere a `NavHost` exists, so the rules are proven by their tests
  and by synthetic projects, not by real code. Apps generated in Phase 5 are the expected beneficiaries.
- **Routes are matched project-wide, not per `NavHost`.** A route declared in one graph satisfies a `navigate` from
  another, so a wrong graph is not caught. `navigate` is only read in files that mention a `NavController`, and
  `popBackStack` is not checked at all (Android does not document it to throw).
- **Type-safe routes** are judged only for a project class annotated `@Serializable` with a plain name; a generic
  `composable<T>` silences the rules. A string `navigate` is not judged against type-safe destinations, nor the
  reverse.
- **XML graphs:** an action target is judged against the destination ids of *all* graphs in the project; `popUpTo`
  is not checked; `findNavController().navigate(R.id.x)` calls are not checked; only fully qualified class names of
  the app's own packages are checked. Safe Args output is not modelled.
- **Duplicate routes** are only reported inside one function body, and Android does not document what happens with
  a duplicate, so the finding says "ambiguous" and is a warning.
- **Deep links:** filters that a `<nav-graph>` element would generate are not expanded, so a Compose URI that only
  such a filter could match is reported. A host-less `https` filter matches every host, so it silences
  `deeplink.uri_not_in_manifest`. A link meant only for in-app use is reported as unreachable from outside, by
  design (a warning). `autoVerify` is only judged for the intent-filter shape; the Digital Asset Links file on the
  web server is not, and could not be, checked.
- **Navigation 3 is deliberately not analysed.**

Phase 4b-2b (security):

- **The call-site rules need a literal target SDK, and most real projects do not write one.** Only `platform-samples`
  (of five) states `targetSdk` as a number. `sunflower` writes `libs.versions.targetSdk.get().toInt()`, `iosched` a
  `buildSrc` constant (`Versions.TARGET_SDK`, which is 30), `AntennaPod`'s app module takes it from a shared script
  (`apply from: "../common.gradle"`), and `nowinandroid` uses convention plugins. In those projects `security.pending_intent_*`, `security.receiver_export_flag_missing` and
  `security.cleartext_url_blocked` stay silent by design. Resolving a catalog version or a `buildSrc` constant would
  fix this, but it reads Gradle more completely than 4b-2b was approved to, and it would also change
  `manifest.exported_missing` (which uses the same target), so it was **not done**; it is the obvious next step.
- **Library manifests cannot be read.** `security.permission_not_declared` therefore says "a library's manifest
  could" declare the permission, and `security.permission_never_requested` can be wrong when an SDK asks for the
  permission itself. The latter is judged only in a module whose own code already requests or checks permissions
  (iosched's `ar` module declares `CAMERA` and relies on ARCore's `ArFragment` to ask; judging it would have been a
  false positive), and a permission mentioned anywhere (code, a resource array) is never reported. A project with no
  permission code at all is therefore never told that a declared permission is unused, even when it is.
- **`permission_not_declared` is a warning with an unverified premise.** The one real-project hit (`AntennaPod`,
  `READ_EXTERNAL_STORAGE`) was checked only as far as "no manifest in the repository declares it"; whether a
  dependency's manifest does could not be determined without a build.
- **Intent security is limited to `PendingIntent` mutability and `registerReceiver` flags.** Not implemented: implicit
  intents to non-exported components, `sendBroadcast` without a permission, `FLAG_GRANT_*` URI grants, WebView
  JavaScript, custom permissions' protection levels, `android:debuggable`, backup rules. Implicit exports (an
  intent filter without `android:exported`, targets below 31) are not judged.
- **Exported services and receivers are only flagged when every action is custom (or there is no filter).** A
  receiver that listens for a system action and a custom one is not reported, nor is anything with an `android.`,
  `androidx.`, `com.android.` or `com.google.` action (media browser and session services, boot receivers).
  Those are treated as platform contracts; an app that really exposes one unprotected is missed.
- **Cleartext coverage is three call shapes** (`baseUrl`, `url`, `URL`) with a literal single argument. `Uri.parse`,
  `WebView.loadUrl`, templated URLs and URLs held in constants are not read. A library that adds
  `usesCleartextTraffic` through its own manifest would make `cleartext_url_blocked` wrong; that merge cannot be
  seen. The rule is silent as soon as *any* manifest or config in the project permits cleartext.
- **Suppressions are honoured coarsely.** An annotation anywhere in a file, or an id disabled anywhere in a Gradle
  script that mentions `disable`/`ignore` within 400 characters, silences the rule for the whole file or project.
  `lint-baseline.xml` is not read.
- **`change.sensitive_permission_added` blocks until approved.** It is an error with `approval="other_high_impact"`:
  a patch that adds `CAMERA` for a camera feature the user asked for is held for approval unless the caller already
  granted it. `QUERY_ALL_PACKAGES` (documented as a `normal` permission) is not in the table.
- Nothing in 4b-2b was compiled or run on a device. Behaviour rests on the documentation and on tests.

- **No known false positive of the 4a rules remains on the five validation projects** (Phases 4a.6 and 4a.7
  fixed the last four). Two limits stay by design:
  - `items(total) { ... }` in a lazy list is judged as the extension that needs its import, because `total` may be
    an `Int` or a list and the call does not say which. Only a named `count =`, an integer literal, or a `.size` /
    `.itemCount` argument selects the member.
  - A wildcard import provides a framework class only if the catalog lists that class. Eight names that exist both as
    Compose or library types and as framework classes are listed (`Surface`, `Color`, `Canvas`, `Path`, `Icon`,
    `Image`, `RadioButton`, `Snackbar`); another such name used with a wildcard import of its framework package would
    still be reported until it is added. The probe that found these checked twenty well-known names, not every class.

## Unfinished integration work

Not done:

- **Phase 4b-2c and 4b-3** (authentication, API-use and null-safety rules).
- **More real-project validation** (see Phase 4 limitations): five projects have been reviewed in total, and the
  older rules still showed false positives on two of the newer ones; more are needed before any finding is
  allowed to block a patch in production.
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
