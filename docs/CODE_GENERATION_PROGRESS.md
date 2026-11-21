# Code Generation Progress (Person 3)

Scope: `packages/agent-core/codegen` (library, `androai_codegen`) and `workers/ai-agent` (Celery adapter).

| Phase | Scope | State |
|---|---|---|
| 0 | Package setup, dev environment, this document | Done |
| 1 | File-editing abstraction and patch engine | **Done, hardened (`5aea805`), verified on Windows and Linux (WSL); not yet in CI** (see Verification) |
| 2 | Git checkpoints, manual vs AI change tracking | **Done, verified on Windows and Linux (WSL); not yet in CI** (see Verification) |
| 3 | Contracts proposal for `CodingTask` / `CodingResult` | **Drafted, awaiting Persons 2 and 4**: [CODEGEN_CONTRACT_PROPOSAL.md](CODEGEN_CONTRACT_PROPOSAL.md). No contracts PR until both approve. |
| 4 | Code review engine | **In progress. 4a done** (syntax, imports, duplicates, resources, patch review), verified on Windows and Linux (WSL) against synthetic fixtures and, on Windows, three real projects (`nowinandroid`: 0 findings, 9 of 9 injected faults caught; `AntennaPod`, Java/Groovy: 2 findings, 10 of 10; `iosched`, Hilt/Data Binding: 0 findings, 10 of 10). Phase 4a.5 added Gradle project-dependency modelling and a faster `ReviewSession`. **4b-1 done**: manifest, Gradle/dependency and change-aware rules plus review against a checkpoint (23 new rule ids; verified on Windows and Linux; 57 of 57 mutations caught; 38 of 43 faults injected into five real projects caught, the other 5 silent on purpose). Phase 4a.6 then fixed two false positives of the older rules that 4b-1's validation turned up (library-shipped resources, a class imported next to an icon property), and Phase 4a.7 the last two (`items(count = n)` and framework classes behind a wildcard import). **4b-2a done** (navigation graphs and deep links: 12 new rule ids, 59 tests, 114 of 114 mutations caught, 49 of 55 injected faults caught on five real projects, nothing reported on them unfaulted). **4b-2b done** (security: 13 new rule ids, 96 tests, 143 of 143 mutations caught; five real projects report one unconfirmed finding unfaulted, and 22 of 33 security faults injected into them are caught, the other 11 silent for reasons that were checked: mostly a target SDK that is not written as a number). **4b-2c done** (authentication: 8 new rule ids, 65 tests, 94 of 94 mutations caught; nothing reported on the five real projects unfaulted, 25 of 33 authentication faults injected into them caught, the other 8 silent because the build is not readable enough). **Target SDK resolution done** (a follow-up: `targetSdk` is now also read from a version-catalog entry or a `buildSrc` constant, so the rules that depend on it engage on `iosched` and `sunflower`; 121 tests, 27 of 27 mutations caught, no new finding on the five real projects, 101 of 121 injected faults caught, up from 96). **4b-3 (API use, null safety) not started**. |
| 5 | New project generation | **In progress. 5.1 done (branch `p3/phase5-templates`, draft PR): Android project templates**, Kotlin + Jetpack Compose, rendered as a `PatchSet` (see "Project templates (Phase 5.1)"). **Build-verified for the default template configuration only** (Docker, 2026-11-20, AGP 9.5.1, Gradle 9.6.0, Kotlin 2.4.21, Compose BOM 2026.11.01, compileSdk 37.1): debug APK, release APK and AAB (both **unsigned**), `build`, `lint` (0 errors, 4 warnings, left as known limitations) and `tasks --all` pass. **The default project (no spec) has no application unit test** (`test` passes with nothing to run), no signing, no other configuration, no Gradle wrapper. **5.2 done (branch `p3/phase5-screens`, pushed, stacked on 5.1): multi-screen projects from a structured `ProjectSpec`** (deterministic, no LLM), build-verified on four sample specs with the same Gradle commands (see "Phase 5.2"); the three-screen sample was also **run once on an Android 17 emulator** (navigation, Back, rotation, logcat; see "Phase 5.2 sample on an emulator"). **5.3 done (branch `p3/phase5-nav-tests`, pushed, draft PR #4): generated navigation tests** for projects with a spec (Robolectric + Compose test, test-only dependencies; see "Generated navigation tests (Phase 5.3)"): the unit tests pass on the four sample specs and fail when the generated navigation is broken (mutation-checked); they simulate API 35 on JDK 17, and no instrumented test exists. **5.4 done locally (branch `p3/phase5-scroll-signing`, not pushed): scrolling screens** (an 8-button screen was unreachable in landscape on an emulator before, reachable after), the tall-screen workaround and the release-test skip removed (the tests pass on the debug and the release task), signing investigated with a throwaway key (see "Scrolling screens, release tests and signing (Phase 5.4)"); Compose previews not verified. Prompt-driven generation, planning and the worker are not started |
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
| `gradle.sdk_order` | warning | `minSdk > targetSdk` or `targetSdk > compileSdk` (literals in one script; a `compileSdk { version = release(N) { minorApiLevel = M } }` block counts) |
| `gradle.duplicate_dependency`, `gradle.conflicting_versions` | warning | the same coordinate twice in one configuration, with or without differing versions |
| `gradle.unplanned_dependency` | error, approval `other_high_impact` | with `ReviewConfig.permitted_dependencies` set, any library outside the plan (entries: group, `group:artifact`, `group:*`) |
| `change.component_removed`, `change.permission_removed`, `change.dependency_removed` | warning | something the project had before is gone. A component matches under any spelling of its class (relative or fully qualified), so a package rename is one finding. A dependency is "removed" only if its coordinate is declared nowhere in the project afterwards |
| `change.integration_removed` | error, approval `remove_integration` | a payment or authentication dependency (`SENSITIVE_DEPENDENCY_GROUPS`) disappeared |
| `change.package_renamed` | error, approval `rename_package` | `applicationId`, `namespace` or the manifest `package` changed |
| `change.language_converted` | error, approval `convert_language` | a `.java` file replaced by a `.kt` file of the same name, or the reverse |
| `change.ui_toolkit_converted` | error, approval `convert_ui_toolkit` | a file that built its screen from XML layouts now uses Compose, or the reverse (judged per file, and only if it stopped using the old toolkit) |
| `change.tests_removed` | warning | fewer `@Test` methods in total than before (moving a test between files is not reported) |
| `change.sdk_changed` | warning | `minSdk` raised, or `targetSdk` / `compileSdk` lowered (for `compileSdk`, 37.1 to 37.0 counts) |
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

- *Premises are checked, not assumed.* The `PendingIntent`, receiver and URL rules need the app's target SDK, written
  as a number or resolved as described under "Target SDK resolution" (a library module is judged by the lowest target
  of the applications of the build; an unreadable one makes it silent), and the URL rule additionally needs every
  shipping manifest parsed, no `usesCleartextTraffic` other than `false`, and any network security config readable and
  not permitting cleartext at all (even for localhost).
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

### Phase 4b-2c: authentication

Deliberately conservative: the rules cover recognised sign-in libraries, OAuth redirect configuration, hardcoded
secrets and private keys, signing passwords and credentials in preferences. **They do not verify an app's
authorization model**, whether the server checks tokens, or whether sign-in is correct. The documented behaviour was
checked before any rule was written: the Credential Manager setup and failure documentation, the AppAuth-Android
README, the Firebase Authentication setup page, the Android security tips, the app-signing guide and the Jetpack
Security release notes. Two findings of that check shaped the rules: the security tips call app-private internal storage
"sufficient for most applications", so a token in `SharedPreferences` is an advisory, not a vulnerability; and
`androidx.security:security-crypto` (`EncryptedSharedPreferences`) has deprecated all its APIs "in favour of existing
platform APIs and direct use of Android Keystore", so no rule recommends it.

Recognised integrations (`AUTH_INTEGRATIONS`): Firebase Authentication, FirebaseUI Auth, Credential Manager, Sign in
with Google (`googleid`), legacy Google Sign-In (Play services), AppAuth and Auth0, each with the packages that mean
"this code signs users in with it" and the artifacts that provide them.

| Rule id | Severity | Reports | Documented basis |
|---|---|---|---|
| `change.auth_dependency_removed_still_used` | error, no approval | a recognised sign-in library the project declared before and declares nowhere now (any module, any version, or a known library that depends on it), while a non-test source still imports its package. Silent if any dependency of the new project cannot be resolved. Granting the removal (`change.integration_removed`) does not clear it: it is the fact that the code no longer builds | `firebase-auth`, `androidx.credentials:credentials` and `net.openid:appauth` coordinates from their setup pages |
| `auth.credential_manager_provider_missing` | warning | the project declares `androidx.credentials:credentials` and imports Credential Manager but declares `credentials-play-services-auth` in no module (judged project-wide, and only when every module's dependencies are readable) | the setup lists both artifacts; the documented failure for a missing second one is a `*ProviderConfigurationException`: "Your app is missing the provider configuration dependency. Most likely, you're missing the credentials-play-services-auth module" |
| `auth.appauth_redirect_not_configured` | warning | an application module whose dependencies include AppAuth, with no `appAuthRedirectScheme` anywhere in its build scripts and no manifest declaring `net.openid.appauth.RedirectUriReceiverActivity` | the README captures redirects "through a manifest placeholder" (`appAuthRedirectScheme`) or by replacing `RedirectUriReceiverActivity` with an intent filter (`tools:node="replace"`). The README does not say what happens when neither is done, so the finding says the scheme "is not configured", not that the build fails |
| `auth.appauth_redirect_scheme_unmatched` | warning | a literal redirect URI (`AuthorizationRequest.Builder(..., Uri.parse("scheme:/..."))`, `.toUri()`, `setRedirectUri`) whose scheme no manifest `<data android:scheme>` and no `appAuthRedirectScheme` value matches (case ignored) | the README's custom-scheme intent filter for the redirect activity |
| `auth.private_key_in_source` | error | a PEM `PRIVATE KEY` block with a real body (an `-----END` marker and at least 60 base64 characters, string concatenation and `\n` escapes allowed) in a Kotlin, Java, XML, Gradle or TOML file outside test source sets | "Never commit API keys to your source code repository"; the app-signing guide: the signing key "must be kept secret" |
| `auth.hardcoded_secret` | warning | a token with a distinctive format (AWS access key id, GitHub, Slack, Stripe live, Google OAuth client secret, `sk-`), or a literal of 16+ characters assigned to a `client_secret` / `api_secret` / `app_secret` / `secret_key`-style name in Kotlin, Java, an XML `<string>`, or a Gradle `buildConfigField`, with letters and digits, enough entropy and no placeholder words | the security tips: an attacker "can decompile the app and find these resources". Google API keys (`AIza...`) and JWTs are deliberately not reported |
| `auth.signing_password_in_build_script` | warning | `storePassword` / `keyPassword` given as a literal in a Gradle script (the debug keystore's `android` excluded) | the signing guide: "When you create a signing configuration, your signing information is included in plain text in your Gradle build files ... you should keep your signing information secure by removing it from the build files" |
| `auth.credential_in_plain_preferences` | warning | `putString("<key>", ...)` on a `SharedPreferences` editor for an explicit credential key (`access_token`, `refresh_token`, `id_token`, `auth_token`, `session_token`, `bearer_token`, `oauth_token`, `jwt`, `password`, `passwd`) in a file that uses no encrypted or Keystore-backed storage | for a password: "don't store passwords on the device". For a token: the security tips suggest the Keystore for credentials only your app uses; worded as an advisory |

**How a finding is judged.**

- *No finding repeats a secret.* A finding carries the kind of secret, the identifier it was assigned to and its length;
  a test checks that no secret, token or key body appears anywhere in a finding.
- *Unreadable means silent.* The dependency rules need every module (or the application module and everything it
  depends on) to be readable: no convention plugin, no `allprojects` / `subprojects` dependencies, no unresolved alias,
  no partly written coordinate. A redirect URI held in a constant or template, a computed
  `appAuthRedirectScheme`, a manifest scheme that is another placeholder, a project with no manifest: none is judged.
- *Preferences need the editor.* A credential key is only reported when the write is made on `edit()`, inside an
  `edit { }` block or on something typed as an `Editor` (so `outState.putString("password", ...)` on a `Bundle` is not),
  in a file that mentions `SharedPreferences` and nothing encrypted (`EncryptedSharedPreferences`, `MasterKey`,
  `KeyStore`, `Cipher`, `Aead`, `Tink`, `encrypt`).
- *Keys survive edits.* Call-site findings are keyed by their name or scheme plus an ordinal among identical ones.
- No new approval kind: nothing here is approvable, and `other_high_impact` is not used.

### Target SDK resolution (Phase 4b follow-up)

Several rules depend on the app's `targetSdk`: `security.pending_intent_mutability` (31+),
`security.pending_intent_mutable_implicit` and `security.receiver_export_flag_missing` (34+),
`security.cleartext_url_blocked` and the platform-default note of `security.cleartext_enabled` (28+),
`security.permission_never_requested` (23+) and `manifest.exported_missing` (31+). The review used to read only a
number written directly after `targetSdk` / `targetSdkVersion`, so on most real projects they were silent.
`ProjectAnalysis.target_sdk_of(script)` now returns `(value, line)` for a script, and every one of those rules goes
through it. It is **not a Gradle evaluator**: nothing is run, no expression is computed, and the only forms read are

| Form | Example | Source |
|---|---|---|
| a number written directly (unchanged) | `targetSdk = 35`, `targetSdkVersion 33` | the script |
| a version-catalog entry converted to a number | `libs.versions.targetSdk.get().toInt()`, `.get().toInteger()`, `Integer.parseInt(libs.versions.targetSdk.get())` / `Integer.valueOf(...)` | the single `libs.versions.toml`; `target-sdk`, `target_sdk` and `target.sdk` keys are reached as `libs.versions.target.sdk` |
| a whole-number constant of `buildSrc` / `build-logic` | `Versions.TARGET_SDK`, `Config.Sdk.TARGET`, a top-level `TARGET_SDK` | a Kotlin `const val` (or a `val` inside an `object`) assigned a bare whole number |

Everything else is unknown, and an unknown target means the rule stays silent: arithmetic (`... + 1`), a catalog
version used as a string, a version table (`{ require = "34" }`), a non-numeric or non-ASCII version, an alias or
constant that does not exist, a constant assigned an expression or a string, a `val` outside an object, a constant
in a comment or outside `buildSrc` / `build-logic`, a constant declared twice with different values, two catalog keys
with the same accessor, a catalog that is missing, broken, not the only `libs.versions.toml` or accompanied by a
custom catalog, `rootProject.ext`, Gradle properties, conditionals, shared scripts (`apply from:`) and convention
plugins. A number written directly still wins; otherwise the first `targetSdk` expression that resolves is used.
`gradle.sdk_order` and `change.sdk_changed` compare several SDK levels and were deliberately **not** changed for target
resolution: they still read only numbers written out, so a target that lives in the catalog is not compared there.
Authentication rules do not depend on the target SDK; only `security.permission_never_requested` (above) does.

**`compileSdk` block (Phase 5.1 follow-up).** The two rules above now also read the AGP 9 form
`compileSdk { version = release(37) { minorApiLevel = 1 } }`, over one line or several: it is how API 37.1 is written,
and a plain `compileSdk = 37` is API 37.0. Before, only a same-line `compileSdk ... release(N)` was recognised (and no
test covered it), so a module using the usual multi-line block was silently skipped by `gradle.sdk_order`. Now the
API level is compared as before (`targetSdk` is a whole API level, so 37 under compile SDK 37.1 is in order), the
finding names the minor level (`compileSdk (36.1)`), and `change.sdk_changed` also reports a drop of the minor level
(37.1 to 37.0). Not read, and still silent: `preview(...)`, a property, a catalog value or arithmetic inside `release(...)`
(a literal `release(N)` is required, so `release(36 + 1)` is unknown rather than 36), and any `minSdk { }` / `targetSdk { }`
block form (whether AGP 9 offers one was not checked).

**Not implemented yet (4b-3):** incorrect API use and null safety.

## Project templates (Phase 5.1)

`androai_codegen.templates` renders a new Android project as a `PatchSet`. One template exists: **Kotlin + Jetpack
Compose**, single module `:app`. It is a deterministic function from a validated `ProjectConfig` to files. It calls
no LLM, plans nothing and writes nothing: `PatchEngine` applies the result, so path safety, protection, journal,
checkpoint and rollback are the existing ones.

> **Verified, for the default configuration only.** On 2026-11-20 the sample project (`Notes App`,
> `com.example.notes`, default config), rendered through `PatchEngine` into an empty workspace, passed these Gradle
> commands in a temporary Docker environment (exact commands, exit codes, sizes and hashes under "Phase 5.1
> verification"): `build`, `assembleDebug`, `assembleRelease`, `bundleRelease`, `lint` (0 errors, 4 warnings), `test`,
> `tasks --all`, and the Compose Preview run-files tasks. Outputs: a debug APK, an **unsigned** release APK and an
> **unsigned** release AAB. `templates/versions.py` records this as `VERIFIED_BUILD`, and a test fails if a pin changes
> without it. **Not verified:** signing (so the release outputs cannot be installed or uploaded as they are), an
> emulator or device run, any application unit test (**none exists in this default project**: the app has no logic of
> its own, so no test was added just to make Gradle report one, and `test` passes with nothing to run; Phase 5.3 later
> generated navigation tests, but only for a project with a spec), any other package name or SDK
> level, and the Gradle wrapper (system Gradle 9.6.0 was used, because the wrapper jar and script are not generated).
> The Python tests prove structure and internal consistency; only the Gradle build proves the project compiles. Two
> earlier results were failures that changed the template: the first build failed on compileSdk 37.0, and `tasks --all`
> failed in AGP's Compose Preview task registration (see "Toolchain decisions").

### Architecture

| Module | Role |
|---|---|
| `config.py` | `ProjectConfig` (frozen pydantic model, `extra="forbid"`), `Language`, `UiToolkit`. Invalid input raises `pydantic.ValidationError`, like an invalid `PatchSet` |
| `validation.py` | Name rules: package, application ID, project name, version name. Reject, never "fix up" |
| `naming.py` | ASCII identifiers derived from the display name (theme function, style name, Gradle root name) |
| `versions.py` | **The only place a version is spelled**: `TOOLCHAIN` pins, default SDK levels, `SOURCES` (where each pin was read) |
| `render.py` | `__NAME__` placeholder substitution (single pass, unknown placeholder is an error), `android_string` escaping |
| `kotlin_compose.py` | The template: 19 files as text with placeholders |
| `renderer.py` | Registry keyed by (language, UI toolkit), `render_files`, `render_patch` (-> `PatchSet` of `CreateFile`) |
| `errors.py` | `TemplateError`, `UnsupportedTemplateError`, `TemplateRenderError` |

Every rendered path goes through the existing `normalize_relative_path` and must come out unchanged; a duplicate path,
a NUL or CR character, or a missing final newline is a `TemplateRenderError`. A placeholder value can therefore not
smuggle in `..`, a backslash, a drive letter, `.git` or a device name, even if a validator were wrong. Output is sorted by
path and contains no date, host name, random id or absolute path: the same config renders the same bytes.

### Inputs (`ProjectConfig`)

| Field | Default | Rule |
|---|---|---|
| `project_name` | required | NFC-normalised display name: letters, digits and combining marks of any script, single spaces and `_ - . ' & , ( ) ! +`; starts with a letter or digit; at most 50 characters. No consecutive spaces (Android collapses them in a string resource). Only `strings.xml` receives it, escaped |
| `package_name` | required | The `namespace` and Kotlin package: at least two segments, each `[a-z][a-z0-9_]*`; no Kotlin hard keyword, Java reserved word or literal (`_` included) or Windows device name; at most 100 characters |
| `application_id` | `package_name` | At least two segments, each starting with a letter, `[a-zA-Z0-9_]`. May differ from the package |
| `language`, `ui_toolkit` | `kotlin`, `compose` | `java` and `xml` are valid values but have no template: rendering raises `UnsupportedTemplateError` naming what is available |
| `min_sdk` | 24 | At least 24 (the floor of the pinned AndroidX libraries) and not above `target_sdk` |
| `target_sdk` | 36 | Between `min_sdk` and the API level of the compile SDK (37 is allowed under 37.1) |
| `compile_sdk`, `compile_sdk_minor` | 37, 1 | The compile SDK is API 37 minor level 1, **API 37.1**, and nothing else: the pinned Compose 1.13.0 libraries declare `minCompileSdk=37` and `minCompileMinorSdk=1`, so API 37.0 fails the AAR-metadata check. 37.2 exists in the SDK manager but is not validated, so it is refused. Both fields are strict integers; the pair is checked against `TOOLCHAIN` as (API, minor). A config that gives only `compile_sdk=37` (or an older dump without the minor field) still validates and gets minor 1 |
| `version_code`, `version_name` | 1, `1.0` | Integer 1 to 2,100,000,000 (strict: no strings or booleans); `[0-9A-Za-z][0-9A-Za-z._+-]*`, at most 40 characters |

### Generated structure (19 files)

```text
.gitignore
build.gradle.kts                    plugins (apply false) + Kotlin Gradle plugin classpath
settings.gradle.kts                 repositories, rootProject.name, include(":app")
gradle.properties
gradle/libs.versions.toml           version catalog: AGP, Kotlin, Compose BOM, activity, navigation
gradle/wrapper/gradle-wrapper.properties   distribution URL and SHA-256 (no jar, no gradlew)
app/build.gradle.kts                namespace, applicationId, SDK levels, Compose, dependencies
app/proguard-rules.pro
app/src/main/AndroidManifest.xml    launcher activity, no permissions, allowBackup="false"
app/src/main/res/values/{strings,colors,themes}.xml
app/src/main/res/values-night/themes.xml
app/src/main/java/<package path>/MainActivity.kt
app/src/main/java/<package path>/ui/theme/{Color,Type,Theme}.kt     Material 3, <Name>Theme
app/src/main/java/<package path>/ui/home/HomeScreen.kt              sample screen with a @Preview
app/src/main/java/<package path>/navigation/AppNavHost.kt           NavHost, one destination
```

### Usage

```python
from androai_codegen.editing import PatchEngine, Workspace
from androai_codegen.review import review_patch
from androai_codegen.templates import ProjectConfig, render_patch

config = ProjectConfig(project_name="Notes App", package_name="com.example.notes")
patch = render_patch(config, project_id="p1", run_id="r1", task_id="t1")   # a PatchSet of CreateFile
review = review_patch(engine, patch)     # writes nothing; the rendered project has no findings
if review.applicable:
    engine.apply(patch)                  # or CheckpointManager.apply(patch) to track it
```

`render_files(config)` returns the same files as `RenderedFile(path, content, description)` for callers that want the
text without a patch. Creating over an existing file fails the whole patch (`already_exists`), as for any create.

### Toolchain decisions

`docs/COMPATIBILITY_MATRIX.md` leaves the Android versions open ("pin one tested pair", "pin per generated-project
template") and still lists compileSdk and targetSdk 35. That does not work with current libraries, so the template pins
what the official sources documented on 2026-11-20 (`SOURCES` in `versions.py` has the detail):

| Item | Pin | Why |
|---|---|---|
| Android Gradle plugin | 9.5.1 | Newest final on Google Maven. AGP 9 has Kotlin built in: the Kotlin Android plugin is **not** applied (applying it on AGP 9 is an error) and `useAndroidX` is on by default |
| Gradle | 9.6.0 (SHA-256 in the wrapper properties) | AGP 9.5's documented minimum and default |
| Kotlin | 2.4.21 | Newest final. Used through the `buildscript` classpath entry that the AGP built-in-Kotlin documentation describes, plus the Compose compiler plugin |
| Compose BOM, activity-compose, navigation-compose | 2026.11.01, 1.13.0, 2.10.2 | Newest finals on Google Maven |
| JDK | 17 | AGP 9.5's requirement |
| compileSdk / targetSdk / minSdk | 37.1 / 36 / 24 | Compose 1.13.0 needs API 37.1 (found by a real build; the docs said only "37"); Google Play requires 36 or higher for new apps; 24 is the floor of the pinned navigation library |

- **compileSdk is API 37.1, found by a real build.** The first build, with `compileSdk = 37`, failed in
  `:app:checkDebugAarMetadata`: the Compose 1.13.0 libraries of BOM 2026.11.01 (`ui`, `foundation`,
  `foundation-layout`, `animation`, `ui-tooling`, `ui-tooling-data`) declare `minCompileSdk=37` **and**
  `minCompileMinorSdk=1` in their `aar-metadata.properties` ("compile against version 37.1 or later"), and an integer
  `compileSdk = 37` is API 37.0. Documentation read earlier said only "37". The template now writes
  `compileSdk { version = release(37) { minorApiLevel = 1 } }`, `ProjectConfig` has `compile_sdk_minor` (default 1), and
  the build environment needs the SDK platform `android-37.1`. The same pins built (36 tasks, no warning) once that was
  changed; no pin was changed. **Alternative that also built** in a throwaway experiment (not adopted): plain
  `compileSdk = 37` with the older BOM 2026.09.00 (Compose 1.12.1, material3 1.4.0), which needs only platform 37.0 but
  is not the newest Compose and breaks again at the next BOM that raises the level. Survey of `ui-android`: 1.11.4
  needs API 35, 1.12.1 needs 37.0, 1.13.0 needs 37.1; AGP's minimum for 1.12 and 1.13 is 9.1.0.
- **Kotlin 2.4.21 with AGP 9.5.1.** Kotlin's own compatibility table lists AGP 8.5.2 to 9.3.1 for Kotlin 2.4.21, below
  the pinned 9.5.1. The build resolved the Kotlin Gradle plugin from AGP's bundled 2.2.10 to 2.4.21 through the
  classpath override, compiled the Kotlin and printed no compatibility warning (`--warning-mode all`). That is evidence
  for this one build, not an official support statement.
- **Compose Preview task registration, found by `gradle tasks --all`.** `gradle :app:tasks --all` (and requesting
  `:app:generateDebugComposePreviewRunfiles` directly) failed in AGP 9.5.1 with "Could not create task ... Compose
  Preview failed ... Android resources are excluded from unit tests (`testOptions.unitTests.isIncludeAndroidResources =
  false`)"; with only that setting changed, the **release** variant failed with "Unit tests are disabled for this variant
  (`enableUnitTest = false` in `beforeVariants`)". Normal builds never create those tasks, so `build`, `check`,
  `assembleRelease`, `bundleRelease`, `lint` and `test` passed regardless; tools that list every task may not have. It
  is not caused by the `ui-tooling` dependency (removing it changed nothing). **Resolution** in the template's
  `app/build.gradle.kts`: `testOptions { unitTests { isIncludeAndroidResources = true } }`, and `androidComponents {
  beforeVariants { variantBuilder -> variantBuilder.hostTests[HostTestBuilder.UNIT_TEST_TYPE]?.enable = true } }` with
  `import com.android.build.api.variant.HostTestBuilder` (the `variantBuilder.enableUnitTest` named in AGP's own message no
  longer exists in AGP 9: "Unresolved reference"). With both, `tasks --all` and `build` pass, and the two Compose
  Preview tasks run when given their output file (`--compose-preview-manifest-file=<path>`, an option the IDE supplies;
  without it the task fails with "Value not set", by design). **Side effect, checked:** unit tests are now enabled for the
  release variant too, so `testReleaseUnitTest` exists and runs (`NO-SOURCE`, as there are no tests), and a test later
  added under `src/test` runs for debug and release. The release APK, the release AAB and the debug APK are
  **byte-identical** to those built before the change (same SHA-256), and `lint` reports the same four warnings.
- **The merged APK carries one permission the template does not declare**: `<applicationId>.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`,
  added by the AndroidX libraries' manifest merge. The template's own manifest declares none.
- **Contract defaults differ.** `AndroidTarget` defaults to 35 and is owned by other people; it was not touched. The
  worker adapter that maps it onto `ProjectConfig` must not pass `compile_sdk=35` (rejected) and should decide what to
  do with a `target_sdk` below 36 (accepted here, but Play will not take it for a new app).
- **Navigation Compose with string routes** (`const val` route constants), not Navigation 3: the review engine's
  navigation rules analyse the former only (see 4b-2a), and Navigation 3 is not analysed.
- **Wrapper**: only `gradle-wrapper.properties`. The wrapper jar is a binary and the patch engine is text-only; `gradlew`
  would need an execute bit the engine does not set. Whatever builds the project must run `gradle wrapper` or use a
  Gradle installation. `PatchSet` cannot carry either file.
- **No launcher icon, no `android:icon`** (lint warns about a missing application icon), `allowBackup="false"`, no
  unit or instrumented test stubs.

**Proposed update to `docs/COMPATIBILITY_MATRIX.md`** (not applied: "change only with team approval"; build owner is
Person 4):

| Item | Proposed |
|---|---|
| JDK | 17 |
| Gradle / AGP | 9.6.0 / 9.5.1 (built and verified 2026-11-20 for the default template configuration; see `VERIFIED_BUILD`) |
| Kotlin / Compose BOM | 2.4.21 / 2026.11.01, pinned in `androai_codegen.templates.versions` |
| compileSdk / targetSdk / minSdk | 37.1 / 36 / 24 for generated projects, with compileSdk written as `compileSdk { version = release(37) { minorApiLevel = 1 } }` (the `AndroidTarget` default of 35 / 35 / 24 does not build with Compose 1.13 and is not accepted for new Play apps; `AndroidTarget` has no minor level) |

### Limitations

- **Verified for the default template configuration only.** See the note at the top of this section. Other package
  names, application IDs, version codes, SDK levels (only min 24 / target 36 / compile 37.1 were built), a build with
  the Gradle wrapper, an emulator or device run, and signing are untested. Both DSL details that were uncertain when
  this was written built under AGP 9.5.1: `buildFeatures { compose = true }`, and the `compileSdk` block (the plain
  `compileSdk = 37` form turned out to be the wrong one, see above).
- **The release APK and AAB are unsigned.** The template has no signing configuration (nothing secret is generated, and
  `*.jks`, `*.keystore` and `keystore.properties` are protected files). `apksigner verify` reports the APK as not
  signed and `jarsigner -verify` finds no manifest in the AAB, so neither can be installed or uploaded to Google Play
  as it is. Release builds are not shrunk (`isMinifyEnabled = false`), so the release APK is 9.3 MB with two
  dex files. Signing is a later phase.
- **The default project has no application unit test.** It has no logic of its own, so no test was generated: an
  empty one would only make Gradle list a test. `test`, `testDebugUnitTest` and `testReleaseUnitTest` all pass with
  `NO-SOURCE`, which verifies nothing about behaviour. Tests belong to the phases that generate real logic: Phase 5.3
  generates navigation tests for a project with a `ProjectSpec` (see "Generated navigation tests (Phase 5.3)").
- **Lint: 0 errors, 4 warnings, left as known limitations and not suppressed** (same for debug and release):
  1. `OldTargetApi`: `targetSdk = 36` is not the latest API level (the config allows 37; 36 is what Google Play requires
     of new apps today, and was a deliberate choice).
  2. `AndroidGradlePluginVersion`: "a newer version of Gradle than 9.6.0 is available: 9.9.2" (reported on
     `gradle-wrapper.properties`). 9.6.0 is AGP 9.5's documented minimum and default; other versions were not tried.
  3. `DataExtractionRules`: `android:allowBackup="false"` is deprecated from Android 12; lint suggests
     `android:dataExtractionRules`. The backup policy was left as it is.
  4. `MissingApplicationIcon`: there is no `android:icon` (no launcher icon is generated).
  Future work: decide each (raise the target, move to a newer Gradle once AGP documents it, add a data-extraction
  rules file, generate a launcher icon). None of the four affects the build.
- **"Unable to strip ... libandroidx.graphics.path.so"** appears in release builds in the validation image because it
  has no NDK (`/sdk/ndk` is absent, "missing strip tool for ABI"); the native library is packaged unstripped. It is
  environmental, not a template problem, and disappears if the build image installs the NDK AGP asks for.
- The template writes `minSdk = N` and `targetSdk = N` as integers, which the review reads. Whether AGP 9 offers
  `minSdk { }` / `targetSdk { }` block forms was not checked; they are neither generated nor read by the review.
- Single module, no flavors, no signing configuration, no `local.properties` (protected), no secrets.
- One template (Kotlin + Compose). Application-ID rules are the documented ones; the Play Store may refuse more.
- The project name is shown through one string resource. A name with no ASCII letters falls back to the identifier
  `App` for the theme and the last package segment for the Gradle root name.
- The review engine reads `.kt .kts .java .xml .gradle .toml .proto`, so the properties, ProGuard and `.gitignore` files
  are generated but not reviewed. Two things the review engine does not catch in this project, checked by changing the
  output: a manifest `@style/` reference to a missing style, and a missing `namespace` in `app/build.gradle.kts`. The
  template tests cover both (see Phase 5.1 verification); the review rules were not changed.
- A project exists only after something applies the patch; nothing here creates a Git repository or a checkpoint.

### Adding a Java or XML-layout template later

1. Add a module next to `kotlin_compose.py` that defines `FILES: tuple[TemplateFile, ...]`, using only placeholders from
   `renderer.placeholder_values` (add new values there, with a test that every value is used).
2. Register `Template(Language.JAVA, UiToolkit.XML, ..., FILES)` in `renderer._REGISTRY`. `Language` and `UiToolkit`
   already have the members; nothing in the config, the validators or the renderer changes.
3. Reuse the Gradle, catalog, wrapper and resource files by importing them from `kotlin_compose.py` (or moving them to
   a shared module) and replace only the source files, the plugin and dependency lines.
4. Add the same kinds of tests (structure, package declarations, review compatibility) and the faults-are-caught
   sentinels of `tests/test_templates_patch.py`.

## Multi-screen projects from a `ProjectSpec` (Phase 5.2)

Phase 5.1 renders one project with one sample screen. Phase 5.2 adds an **internal, deterministic spec-to-project layer**:
a validated `ProjectSpec` (which screens exist, what each shows, which screen opens which) is rendered into the same
Kotlin + Compose project, as one `PatchSet`. No LLM, planner, Celery worker, storage or repair loop is involved, and no
contract, compatibility matrix, worker or Docker file was touched. A later adapter (Person 3, once Person 2's
`ImplementationPlan` shape and the v0.2 contract are agreed) maps a plan onto a `ProjectSpec`; none of that exists yet.

| Module | Role |
|---|---|
| `spec.py` | `ScreenSpec` and `ProjectSpec` (frozen pydantic models, unknown fields refused), name and route derivation, graph validation |
| `screens.py` | `apply_spec`: turns the rendered Phase 5.1 files into the project of a spec (Kotlin, `Routes`, navigation host, strings) |
| `renderer.py` | `render_files(config, spec=None)` and `render_patch(config, ..., spec=None)`; `Template.apply_spec` is how a template supports a spec (one without it refuses with `UnsupportedTemplateError`) |
| `render.py`, `validation.py` | `checked_file` (generated files get the same path and content rules as template files) and `validate_display_text` (shared by project names and screen texts) |

### Inputs

| Field | Rule |
|---|---|
| `ScreenSpec.name` | PascalCase ASCII (`[A-Z][A-Za-z0-9]*`), at most 30 characters, not ending in `Screen`, unique ignoring case. Everything in the code derives from it: the composable `<Name>Screen`, the file `ui/screens/<Name>Screen.kt`, the route (snake case, `SettingsDetail` is `settings_detail`) and the constant (`SETTINGS_DETAIL`). Names that are keywords in lower case (`Class`, `Object`, `Fun`) are fine, as nothing lower-cased becomes an identifier |
| `ScreenSpec.title` | Display text (the rules of a project name), at most 40 characters; shown as a headline and on the buttons that open the screen |
| `ScreenSpec.description` | Optional display text, at most 120 characters, shown under the title |
| `ScreenSpec.navigates_to` | Up to 8 screen names: each must exist, none is the screen itself, none is repeated; one button each |
| `ProjectSpec.screens` | 1 to 12 screens |
| `ProjectSpec.start` | A screen name; defaults to the first screen. **Every screen must be reachable from it** (an island is refused, listed by name) |

Titles and descriptions only ever reach `strings.xml`, escaped. A string is written only if something uses it (no unused
resource for lint): `screen_<route>_title`, `screen_<route>_body` when there is a description, and `action_back` when
some screen is not the start.

### What changes compared with Phase 5.1

With a spec, the sample `ui/home/HomeScreen.kt` is removed, `navigation/AppNavHost.kt` and `res/values/strings.xml` are
replaced, and one `ui/screens/<Name>Screen.kt` is added per screen: 18 + N files. **Every other file is byte-identical**
(Gradle files, catalog, wrapper properties, manifest, theme, `MainActivity`). Without a spec the output is exactly the
Phase 5.1 project: a test pins the SHA-256 of three configs, taken from the 5.1 renderer before 5.2 touched it. The two
shared helpers extracted from `render_template` (`check_rendered_path`, `check_content`) keep its messages.

### Navigation

- Routes are `const val` strings in `object Routes`, and every `navigate` call, `composable(...)` and the start destination
  names one of those constants. No route is computed and nothing is a string template, so the static navigation rules
  (4b-2a) engage: tests assert the review finds every declared route, the start destination and every `navigate` target,
  with `dynamic = False`, and the generated projects have no finding.
- Each screen takes a callback per button (`onOpen<Target>`) and, unless it is the start, `onBack`; `AppNavHost` wires them
  (`navController.navigate(Routes.X)`, `navController.popBackStack()`). A screen with nothing to wire keeps the simple
  `fun XScreen(modifier: Modifier = Modifier)` signature. Each screen has a `@Preview` in the app's theme.
- Plain `Scaffold`, `Column` and `Button`s are used: no `TopAppBar` (chosen to avoid a possible experimental-API opt-in;
  not checked against material3 1.5.0), and no new dependency.

### Usage

```python
from androai_codegen.templates import ProjectConfig, ProjectSpec, ScreenSpec, render_patch

config = ProjectConfig(project_name="Notes App", package_name="com.example.notes")
spec = ProjectSpec(screens=(
    ScreenSpec(name="Home", title="Home", navigates_to=("Settings", "About")),
    ScreenSpec(name="Settings", title="Settings", navigates_to=("About",)),
    ScreenSpec(name="About", title="About"),
))
patch = render_patch(config, project_id="p1", run_id="r1", task_id="t1", spec=spec)   # one PatchSet of CreateFile
# review_patch(engine, patch), then engine.apply(patch) or CheckpointManager.apply(patch), as for any patch
```

### Limitations

- **The screens are static**: a title, an optional description and buttons. No input, state, ViewModel, list, image,
  route argument, deep link, bottom bar or drawer. Navigation is forward buttons plus Back.
- Routes are derived from names and cannot be chosen. At most 12 screens and 8 buttons per screen. English "Back" only.
- Only the Kotlin + Compose template supports a spec; Java or XML combinations still refuse.
- **Run once, not widely**: the apps were built in Docker; the **three-screen sample** was also installed and driven on one
  Android 17 (API 37.0) emulator (see "Phase 5.2 sample on an emulator"): navigation, Back, rotation and logcat passed there.
  Other samples, other devices and API levels, dark mode and the Compose previews in an IDE were not run.
- Phase 5.2 generated no unit test; Phase 5.3 adds navigation tests to a project with a spec (see below). The release APK
  and AAB are unsigned.
- The static review is silent when a route is computed, so a `Routes` constant that is removed by hand would make the
  route "computed" and unreported; the compiler (the Gradle build) is what catches that, and the sentinel tests use literal
  routes for the same reason.
- `ProjectSpec` is not yet produced from anything: mapping a planner's output onto it, and `AndroidTarget` onto
  `ProjectConfig`, is future adapter work that depends on other owners.

## Generated navigation tests (Phase 5.3)

Until Phase 5.2 a generated project had no test: `gradle test` ran with `NO-SOURCE`. A project rendered **from a
`ProjectSpec`** now also contains a real JVM test, `app/src/test/java/<package>/navigation/NavigationTest.kt`, generated
from the spec, and the test-only dependencies it needs. Still deterministic and internal (no LLM, planner, worker, storage,
contract, compatibility-matrix or Docker file was touched). **Without a spec the output is exactly the Phase 5.1 project**
(the three pinned SHA-256 values still hold), so a project without screens has neither tests nor test dependencies.

| Module | Role |
|---|---|
| `navtests.py` | `add_navigation_tests`: the test class, the catalog and `app/build.gradle.kts` additions; `navigation_tests_supported(config)` |
| `renderer.py` | the registered `apply_spec` of the Kotlin + Compose template is now "the screens of the spec (5.2), then their navigation tests (5.3)" |
| `screens.py` | `AppNavHost(modifier, navController = rememberNavController())` (new optional parameter, see below); `BACK_TEXT` |
| `versions.py` | pins `junit`, `robolectric` and `robolectric_sdk`; `VERIFIED_BUILD` extended |

### What the test checks (Robolectric + Compose test + the Navigation test helper)

It composes the real `AppNavHost` in the app's theme with a `TestNavHostController` and, **for the spec it was generated
from**:

- the start screen is shown (`startsOn<Start>`), and the system Back on it leaves the app (`backOnTheStartScreenLeavesTheApp`);
- every screen shows its title, its description when it has one, and **exactly its buttons**: the number of clickable nodes
  and the number carrying each label are asserted, and the controller's route is the screen's `Routes` constant (`shows<Name>`
  and the `assertOn<Name>` helper every other test ends with);
- every button opens its target (`<from>Opens<To>`: one test per edge of the graph, reaching the source screen by the shortest
  way from the start, found breadth-first in button order);
- Back, the on-screen button and the system's, returns to the screen the button was pressed on (not to the start), and an edge
  that leads back into the start screen is left with the system Back only (the start has no Back button).

Texts are looked up through the string resources the screens use, never written into Kotlin. Two screens may share a title
and a screen may itself be called "Back": the n-th button with equal text is clicked, in layout order (this is computed from the
spec and checked by a simulator in the Python tests). Function names are unique (a number is appended if two would collide).

### Dependencies (test-only, approved)

| Library | Version | How |
|---|---|---|
| `org.robolectric:robolectric` | **4.18.1** (`TOOLCHAIN.robolectric`) | `testImplementation` |
| `junit:junit` | **4.13.2** (`TOOLCHAIN.junit`) | `testImplementation` |
| `androidx.navigation:navigation-testing` | **2.10.2** (shares `navigationCompose`, bumped together with Navigation Compose) | `testImplementation` |
| `androidx.compose.ui:ui-test-junit4` | **1.13.0**, from the Compose BOM 2026.11.01 | `testImplementation` |
| `androidx.compose.ui:ui-test-manifest` | **1.13.0**, from the Compose BOM | `debugImplementation` |

Correction of the Phase 5.3 plan: it said the BOM does not manage the `ui-test-*` artifacts. It does (`compose-bom-2026.11.01.pom`
lists `ui-test-junit4` and `ui-test-manifest` at 1.13.0), so they are declared like every other Compose library of the catalog,
without a version, and resolve to exactly the approved 1.13.0. No existing pin changed.

### What real builds changed (findings, in the order they appeared)

1. **Robolectric 4.18.1 cannot simulate API 36 on JDK 17.** The first run failed with "Failed to create a Robolectric sandbox:
   Android SDK 36 requires Java 21 (have Java 17)", because Robolectric runs the app's `targetSdk` (36). The generated project
   builds on JDK 17 (AGP 9.5.1's minimum), so no version was changed; the test pins `@Config(sdk = [35])`, the highest level that
   runs there (`TOOLCHAIN.robolectric_sdk`). A project whose **`minSdk` is above 35** cannot run it at all (a real run with
   minSdk 36 failed every test in `ShadowPackageParser`); such a project is rendered **without** the test and the test
   dependencies (`navigation_tests_supported`), not with tests that fail.
2. **The release unit-test task cannot run the tests.** `debugImplementation(ui-test-manifest)` is what registers the
   `ComponentActivity` that a Compose test launches; `testDebugUnitTest` passed (7 of 7 on the three-screen sample) and
   `testReleaseUnitTest` failed 7 of 7 with "Unable to resolve activity". Declaring the library as `testImplementation`
   instead failed both variants (the manifests of test-classpath libraries are not merged), and `releaseImplementation` would
   put it in the release APK. The release task has to stay registered (AGP 9.5.1 needs release unit tests enabled to create the
   Compose Preview tasks, see 5.1), so `app/build.gradle.kts` **skips that one task by name**
   (`enabled = name != "testReleaseUnitTest"`): `gradle test` runs the debug tests and reports the release task as SKIPPED. A
   check after the change: `tasks --all` and the release Compose Preview run-files task still pass. **Resolved in Phase 5.4**
   (below): the skip is gone and the test runs on both variants.
3. **`createAndroidComposeRule` is deprecated in Compose 1.13.0** (a Kotlin warning); the test uses the `v2` package
   (`androidx.compose.ui.test.junit4.v2`), whose rule runs coroutines on a `StandardTestDispatcher`.
4. **`AppNavHost` takes an optional controller.** The test needs the controller to read the current route, so the generated host
   is `AppNavHost(modifier, navController: NavHostController = rememberNavController())`. `MainActivity` is byte-identical and
   still calls `AppNavHost()`. The static navigation rules still see every route, the start destination and every `navigate`
   target (`dynamic = False`).
5. **The test used a tall screen** (`@Config(qualifiers = "w411dp-h914dp")`) because the generated screens were a plain
   `Column` that did not scroll. **Removed in Phase 5.4** (below): the screens scroll and the test uses Robolectric's default.
6. The first `gradle test` downloads Robolectric's instrumented Android jar for API 35 (about 207 MB) from Maven Central.

### Limitations

- **Behaviour is checked on one simulated Android level** (API 35, by Robolectric on JDK 17), at one screen size, in the light
  theme. It is a JVM simulation, not a device: `Robolectric` is not the emulator run described under "Phase 5.2 sample on an
  emulator", and nothing here covers gestures, animations, the real window manager or other API levels.
- A project with `minSdk` above 35 has no navigation tests (see finding 1). A project built on JDK 21 could run API 36, but the
  generated build is JDK 17 and nothing here assumes otherwise.
- *(Phase 5.3 as written; both items below are resolved by Phase 5.4.)* **The generated screens did not scroll**: a screen
  with 8 buttons did not fit in landscape (reproduced by hand and on the emulator in 5.4), the tests used a tall screen, and the
  release unit-test task was skipped.
- The tests only know what the spec says. They do not test an app that has been edited afterwards, and they stay correct only
  while `MainActivity`, `AppNavHost` and the screens keep the shape the generator wrote.
- The instrumented (`androidTest`) form is not generated: it needs an emulator or device, which neither the build container nor a
  CI runner without KVM has.

## Scrolling screens, release tests and signing (Phase 5.4)

Phase 5.4 fixes what the Phase 5.3 tests exposed and a hand test confirmed: on the 12-screen sample, in landscape, the first
screen's eight buttons were cut off at Step 4 and mouse or touch scrolling did nothing. Branch `p3/phase5-scroll-signing`,
based on `p3/phase5-nav-tests` at `aac94e1`. Deterministic and internal; no pin, contract, worker or Docker file changed.

| Change | Where |
|---|---|
| Every generated screen scrolls: `Modifier.fillMaxSize().padding(innerPadding).verticalScroll(rememberScrollState()).padding(24.dp)` | `screens.py` |
| The generated test scrolls to every button before it taps it and to every title before it checks it is shown (`performScrollTo`) | `navtests.py` |
| The tall-screen workaround (`@Config(qualifiers = "w411dp-h914dp")`) is removed | `navtests.py` |
| The test registers `ComponentActivity` with Robolectric itself (rule `activityRegistration`, `order = 0`, before the Compose rule), so the release unit-test task is no longer skipped | `navtests.py` |
| `VERIFIED_BUILD` records both unit-test tasks, the scroll and the signing investigation | `versions.py` |

**Why the scroll is where it is.** It sits after the system-bar padding and before the content padding, so nothing is clipped
under the bars, and `fillMaxSize()` before it keeps the content centred when it fits (a screen with few buttons looks as before).
The scroll position of a screen is kept when Back returns to it, which is right for users and is why the test scrolls to a
title before checking it. Only generated screens change; the Phase 5.1 sample screen (no spec) and a project without a spec are
byte-identical to before.

**The test now checks the scrolling.** `performScrollTo` fails on a node that has no scroll container, so removing the scroll
from a generated screen makes tests fail (two Kotlin mutants, below). On Robolectric's default small screen the 12-screen sample
went from 15 of 40 failures (Phase 5.3's finding) to 0 of 40, but only after the test itself scrolled: scrolling alone, with
the old test that taps without scrolling, still failed the same 15.

**Release unit tests (investigated, then adopted).** Phase 5.3 skipped `testReleaseUnitTest` because `ui-test-manifest` is
debug-only. A throwaway copy of the three-screen sample with the registration rule and without the skip passed **7 of 7 on both
the debug and the release task**, both with `ui-test-manifest` kept and with it removed. The rule was adopted. `ui-test-manifest`
stays declared (one of the five approved dependencies); for these JVM tests it is now redundant, and dropping it would be your call.

**Signing (investigated only; nothing is generated).** With a throwaway key created in the build container and deleted afterwards,
a copy of the three-screen sample got an optional block at the end of `app/build.gradle.kts` that reads `keystore.properties`
(`storeFile`, `storePassword`, `keyAlias`, `keyPassword`) and, only if the file exists, defines a `release` `signingConfig`. It needs
`import java.util.Properties` at the top (writing `java.util.Properties()` fails in a Gradle script, because `java` is the
Java extension there). Result: without the file the build is unchanged (`app-release-unsigned.apk`, `apksigner` does not verify,
exit 0); with it `assembleRelease` gives `app-release.apk` that **`apksigner verify` accepts** (v2 scheme; minSdk 24 needs no v1)
and zipalign accepts, `bundleRelease` gives an AAB that **`jarsigner -verify` accepts**, and the `classes.dex` is identical to the
unsigned build's. The generated `.gitignore` already ignores `keystore.properties` and `*.jks`. **Not decided**: whether to generate
this block, who owns a real key, Play App Signing, key storage in CI; those are your decisions, and a real key must never be
in a repository or in a generated file.

### Limitations (Phase 5.4)

- **Compose previews are not verified.** Gradle only creates the preview run-files tasks (they pass); rendering needs Android
  Studio, and nobody has looked at one yet. Every screen still has its `@Preview`.
- The emulator checks ran on one emulator (Pixel 8 profile, Android 17, API 37.0, x86_64) with the sizes, rotation, dark mode and font
  scale listed below; other devices, API levels and a physical phone are untested.
- A screen is one scrolling column: no sticky Back button, no scrollbar, no tablet or two-pane layout. A long list of buttons in
  landscape needs scrolling by design.
- `ui-test-manifest` is declared but redundant for the JVM tests (see above).
- Lint now reports **5 warnings**, not 4: Google published AGP 9.5.2 on or before 2026-11-21, so "a newer version of
  com.android.application than 9.5.1 is available" joined the existing "newer Gradle (9.9.2)" notice, both `AndroidGradlePluginVersion`.
  The pins are unchanged on purpose.
- The generated `app/build.gradle.kts` still says "no test exists yet" in a comment of the Phase 5.1 template, which is not true
  for a project with a spec (the comment is part of the byte-identical default project and was left alone).

## Generation workflow, supported technologies, repair rules

**Mostly not implemented yet** (Phase 5.3 and later, 6-8). Phases 5.1 and 5.2 added the project templates and the
deterministic spec-to-project layer above; nothing generates code from a prompt yet. Planned per the
Role 3 spec: Kotlin first with Jetpack Compose, then Java and XML layouts, and a repair loop bounded by iteration, time,
cost, repeated-error and no-progress limits, returning infrastructure and provider failures to orchestration without
touching source. The patch engine is language-agnostic: it edits UTF-8 text files and knows nothing about Kotlin or
Gradle.

## Verification

Results below are for `p3/review-engine` (Phase 4a, the patch-engine hardening, the real-project fixes, 4b-1, 4b-2a, 4b-2b, 4b-2c and the target SDK resolution).

| Platform | Commit | `pytest packages/agent-core/codegen` | Ruff |
|---|---|---|---|
| Windows 10, Python 3.12.10, Git 2.56.1 | Target SDK resolution (the commit that added this row) | **964 passed, 5 skipped, 1 xfailed** (about 2.3 min) | `ruff check` clean; `ruff format --check` clean (78 files); `compileall` clean |
| Linux (WSL Ubuntu, Python 3.14.4, git 2.53.0, ext4), working-tree export | Target SDK resolution | **968 passed, 1 skipped, 1 xfailed** (about 46 s) | `ruff check` clean; `ruff format --check` clean (Linux ruff counted 79 files; both trees hold the same 78 `.py` files); `compileall` clean |
| Windows / Linux | `d549a35` (Phase 4b-2c) | 843 passed, 5 skipped, 1 xfailed / 847 passed, 1 skipped, 1 xfailed | clean (77 files) |
| Windows / Linux | `69254e1` (Phase 4b-2b) | 778 passed, 5 skipped, 1 xfailed / 782 passed, 1 skipped, 1 xfailed | clean (74 files) |
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

### Phase 4b-2c verification

- **65 new tests** (`tests/test_review_auth.py`): every rule has a positive case and the twins that must stay quiet
  (the compliant form, the unreadable form, the premise that does not hold, test source sets, each documented
  exemption). The known-good sample project still reports nothing, helpers assert no `review.internal_error`, and one
  test checks that no finding contains a secret, a token or a key body.
- **Mutation check: 94 of 94 caught** for the 4b-2c code (facts, rules, the change rule and the new
  dependency-coordinates method), and the earlier suites still pass after this slice's changes to `analysis.py` and
  `changes.py`: 114 of 114 (4a.6 to 4b-2a), 22 of 22 (4a) and 143 of 143 (4b-2b). The first run caught 89 of 94
  although all 61 tests passed. Of the five survivors,
  two were code (a length guard that duplicated the pattern's own `{16,}` quantifier, an equivalent mutant, removed; a
  one-finding-per-line guard that hid a second token on the same line, removed) and three were missing tests (an
  unreadable module outside the application's closure, a manifest placeholder whose Gradle value does not match, a
  placeholder written with `put(...)`). Two tests written for those survivors **failed** and exposed a real defect:
  the "computed placeholder" pattern ended in `\s*` followed by a negative lookahead, so the regex engine
  backtracked the whitespace away and every literal `appAuthRedirectScheme = "value"` was treated as computed. The
  redirect rule was therefore silent for any placeholder written with a space, and no earlier test noticed because
  they all asserted silence. A possessive quantifier fixes it and a mutation now covers it.
- **Real projects, no faults (5): no authentication finding.** The only security-group finding is still the
  unconfirmed `AntennaPod` `READ_EXTERNAL_STORAGE` one. The real code exercised the guards: `iosched`'s
  `keyPassword = "android"` is the debug keystore (silent by design), `AntennaPod`'s signing passwords come from
  `project.getProperties().getOrDefault(...)` (an expression, not a literal), and its one credential-like
  `putString("password", ...)` is `outState.putString` on a `Bundle` (not a preferences editor), which is why the
  rule requires the editor context.
- **Real projects, faults injected in memory (121 faults over the five projects, 33 of them new): 96 caught, 25
  silent.** The 33 new authentication-scope faults: 25 caught, 8 silent. Caught on every project that has an
  application module: a private key, a hardcoded client secret, a GitHub token, a literal signing password, a
  refresh token in plain `SharedPreferences`, an AppAuth redirect no filter receives, and (`iosched`) removing the
  FirebaseUI Auth dependency while the code still imports Firebase Auth classes (both `change.integration_removed`
  and the new rule fire). The 8 silent ones are AppAuth-without-a-redirect-scheme
  and Credential-Manager-without-its-provider on four projects, all explained by the readability gates that were
  checked rather than assumed: `iosched` and `sunflower` declare dependencies in `allprojects` / `subprojects`,
  `platform-samples`' and `AntennaPod`'s `app` modules depend on modules that cannot be read, and Credential Manager
  is judged project-wide. `AntennaPod`'s `app-wearos` module *is* readable, and injecting AppAuth there is caught
  (`auth.appauth_redirect_not_configured`) and goes quiet once the placeholder is added: the only real-project
  evidence for that rule. `nowinandroid` has no readable application module (convention plugins), so none of the new
  faults could be injected there.

### Target SDK resolution verification

- **121 new tests** (`tests/test_review_target_sdk.py`, many parametrised): every supported way of writing the target
  (a number, a catalog version in five spellings, `buildSrc` and `build-logic` constants in four shapes) resolves to
  the right number and the right line; 18 forms that must stay unknown do; and each affected rule is checked at its
  boundary SDK level (quiet one level below, reporting at the threshold) through **every** mechanism: 31 for
  `PendingIntent` mutability, 34 for the mutable-implicit and receiver-flag rules, 28 for plain-HTTP URLs and the
  cleartext note, 23 for `permission_never_requested`, 31 for `manifest.exported_missing`. Projects whose target cannot
  be resolved behave exactly as before, a library is judged by its own resolved target or else its application's, and
  `gradle.sdk_order` / `change.sdk_changed` are pinned as unchanged.
- **Mutation check: 27 of 27 caught** for the resolver and its three call sites. The first run caught 24: two anchors
  matched in two places and were made unique, and one mutation survived because, for an application module, the
  module-level and the application-level lookup give the same answer; a test with a library that resolves its own
  target now tells them apart. Two guards that no input could distinguish from their absence (a check on
  `catalog.error`, which already yields no versions, and an identifier pattern in front of a dictionary lookup) were
  removed rather than kept. The earlier suites were re-run against the final code and all still catch everything:
  114 of 114 (4a.6 to 4b-2a), 143 of 143 (4b-2b), 94 of 94 (4b-2c) and 22 of 22 (4a), so **400 of 400** in all. One
  4b-2b mutation first reported "anchor not found" because it targeted the line this change replaced; its anchor was
  updated and it is caught.
- **Real projects: the resolution works and nothing new is reported.** `iosched`: all 6 scripts that mention `targetSdk`
  resolve to 30 through `Versions.TARGET_SDK`; `sunflower`: both resolve to 34 through the catalog; `platform-samples`
  (37) and `AntennaPod`'s `app-wearos` (36) were already numbers and are unchanged; `AntennaPod`'s `app` module
  (shared script) and `nowinandroid` (convention plugins) stay unresolved. Every rule was run on all five projects
  and the findings are **identical** to before the change (`gradle.duplicate_dependency` x3, `import.missing`,
  `import.duplicate`, and the unconfirmed `AntennaPod` `READ_EXTERNAL_STORAGE` finding), so there is no new
  false positive to explain. That is also the evidence for `manifest.exported_missing` on `sunflower` (target 34): the
  rule is now live there and finds nothing in its manifest.
- **Faults injected in memory: 101 of 121 caught (was 96).** The five newly caught: on `sunflower` (target 34) the
  mutable implicit `PendingIntent`, the `registerReceiver` without an export flag, the plain-HTTP `baseUrl` and the
  dropped `android:exported`; on `iosched` (target 30) the plain-HTTP `baseUrl`. The 20 silent ones were each checked.
  Three are correct *because* the target is now known: `iosched` really targets 30, below the Android 12 and 14
  thresholds, so its dropped `exported`, mutable-implicit and receiver faults are not violations. The rest are the
  readability gates described under 4b-2c (AppAuth and Credential Manager on four projects), `AntennaPod`'s `app`
  target in a shared script and its cleartext configuration, and the older 4b-1 and 4b-2a cases.

### Phase 5.1 verification (project templates; `p3/phase5-templates`, three local commits on top of `467b82f`)

| Check | Result |
|---|---|
| Windows 10, Python 3.12.10: `pytest packages/agent-core/codegen` | 1503 passed, 5 skipped, 1 xfailed (the 964 / 5 / 1 of `467b82f` plus 539 new tests) |
| Linux (WSL Ubuntu, Python 3.14.4, ext4), same suite from a fresh export of the working tree | 1507 passed, 1 skipped, 1 xfailed |
| `ruff check`, `ruff format --check`, `compileall` | clean on both platforms |
| New tests | 539 in six files: validation 206, config 96, render 59, Kotlin/Compose template 91, patch and review compatibility 40, review of the `compileSdk` block 47 |
| Mutation testing (each mutation must fail a test) | Templates: 120 of 120 caught (the first run caught 114 of 115; the survivor changed the JDK pin, so a test of AGP 9.5's JDK 17 floor was added). `compileSdk` 37.1 work: 41 of 41 caught (36 on the first run: four patterns did not match because the tracked files use CRLF, and one mutant was equivalent under the current pins until a test with a widened minor range pinned it) |
| Review engine on five real projects (nowinandroid, iosched, sunflower, platform-samples, AntennaPod), `467b82f` against the working tree | Identical reports (same 37 lines, same findings; none from `gradle.sdk_order`, `change.sdk_changed` or an internal error). None of the five uses the `compileSdk` block, so no behaviour changes there, as expected |
| Mutation testing of the Compose Preview regression tests | 15 of 15 caught (import removed, doubled or wrong; `testOptions` removed; Android resources off; `androidComponents` removed, reordered, filtered to debug, disabled or using the removed `enableUnitTest`; a test dependency or test stub added; unbalanced brace; signing config or flavors added). One mutation survived once because it was too subtle to change the generated blocks; it was redone as a real reordering and caught |
| **Gradle builds of the generated project** | **Two failures that changed the template, then every command below passed** (below) |

The 5 Windows skips and the Linux skip are the existing platform-specific tests listed below; the xfail is the existing
one. The new tests need no `git` except one `CheckpointManager` test, which skips without it.

**Gradle builds (Docker, 2026-11-20).** A temporary image on `eclipse-temurin:17-jdk-jammy` (Temurin 17.0.21) with Gradle
9.6.0 and the Android command-line tools 15859902, each download checked against its published SHA-256, and the SDK
packages `platforms;android-37.0`, `platforms;android-37.1`, `build-tools;36.0.0` and `platform-tools` (SDK licences were
accepted inside the temporary container volume only). System Gradle was used, because the wrapper jar and script are not
generated. The Dockerfile and volumes are outside the repository (nothing of Person 4's was touched).

| Build | `compileSdk` | Result |
|---|---|---|
| 1. The Phase 5.1 template as first committed (`7b07126`), rendered through `PatchEngine` | `compileSdk = 37` (API 37.0) | **FAILED** after 2m56s in `:app:checkDebugAarMetadata`: six Compose 1.13.0 AARs require API 37.1 or later (`minCompileSdk=37`, `minCompileMinorSdk=1`) |
| 2. The corrected template, rendered through `PatchEngine` into an empty workspace (19 files; only `app/build.gradle.kts` differs from build 1, so no pin changed) | `compileSdk { version = release(37) { minorApiLevel = 1 } }` | **BUILD SUCCESSFUL**, exit 0, 36 tasks, 36s, no warnings |

Build 2 produced `app/build/outputs/apk/debug/app-debug.apk` (13,314,159 bytes, SHA-256 `834ac583...e26b`): package
`com.example.notes`, versionCode 1, versionName `1.0`, minSdk 24, targetSdk 36, compileSdk 37 (API 37.1, which `aapt2`
prints as 37), launchable activity `com.example.notes.MainActivity`, label `Notes App`, debuggable, AGP 9.5.1 recorded in
the APK's app-metadata. Resolved by Gradle: Kotlin Gradle plugin 2.2.10 (AGP's own) replaced by 2.4.21, Compose compiler
plugin 2.4.21, Compose BOM 2026.11.01 (ui 1.13.0, material3 1.5.0), activity-compose 1.13.0.

**Release, lint, test and the Compose Preview fix.** Build 2's template was then checked with the commands below (same
image; `G` = `gradle --no-daemon --console=plain --stacktrace --warning-mode all`; project A and project B are two fresh
renders through `PatchEngine`; A ran `build` on an empty tree, B ran the other commands). The first four rows are the
checks of the earlier template (`bb79a76`, before the Compose Preview fix); the rest are the template of the third commit.

| Template | Command | Exit | Result |
|---|---|---|---|
| `bb79a76` | `G :app:assembleRelease` | 0 | BUILD SUCCESSFUL, 47 tasks, 1m38s; includes `lintVitalRelease` |
| `bb79a76` | `G :app:bundleRelease` | 0 | BUILD SUCCESSFUL, 50 tasks, 19s |
| `bb79a76` | `G lint` / `G :app:lintRelease` | 0 / 0 | 0 errors, 4 warnings each |
| `bb79a76` | `gradle ... :app:tasks --all` and `G :app:generateDebugComposePreviewRunfiles` | **1 / 1** | "Could not create task ... Android resources are excluded from unit tests"; with only that setting changed the release variant failed too ("Unit tests are disabled for this variant"); also `G :app:testReleaseUnitTest` exit 1, the task did not exist |
| third commit | `G build` (A, empty tree) | 0 | BUILD SUCCESSFUL, 105 tasks, 1m17s; unit-test tasks `NO-SOURCE` for debug and release |
| third commit | `G tasks --all` and `G :app:tasks --all` | 0 / 0 | the Compose Preview tasks are created and listed for both variants |
| third commit | `G :app:generateDebugComposePreviewRunfiles` and the release one, **with no option** | **1 / 1** | "Value not set: `composePreviewManifestFile`" / "Missing required option --compose-preview-manifest-file=<path>": the task needs an output path, which the IDE gives it (`gradle help --task` documents the option); this is not a build task |
| third commit | the same two tasks with `--compose-preview-manifest-file=<path>` | 0 / 0 | BUILD SUCCESSFUL; wrote a 16,756-byte (debug) and a 16,308-byte (release) manifest JSON naming the package, the resource APK of the unit-test packaging task and the classpath |
| third commit | `G assembleDebug` | 0 | BUILD SUCCESSFUL, 36 tasks, 25s |
| third commit | `G assembleRelease` | 0 | BUILD SUCCESSFUL, 47 tasks, 39s |
| third commit | `G bundleRelease` | 0 | BUILD SUCCESSFUL, 50 tasks (10 executed), 13s |
| third commit | `G lint` and `G :app:lintRelease` | 0 / 0 | **0 errors, 4 warnings** each (the same four, below) |
| third commit | `G test`, `G :app:testDebugUnitTest`, `G :app:testReleaseUnitTest` | 0 / 0 / 0 | all `NO-SOURCE`: there are no unit tests, so nothing was run |

Artifacts (the third commit's template; byte-identical to those built before the Compose Preview fix, so the fix changed
nothing that ships):

| File | Bytes | SHA-256 |
|---|---|---|
| `app-release-unsigned.apk` | 9,340,718 | `d7609b6c071d8809ddccff984463502a8e494f2d1030fcbe88973769a876b25a` |
| `app-release.aab` | 8,960,611 | `1170650e74ada1a0498365b85119724cee33c0c1de3a434f74952cf2856799c4` |
| `app-debug.apk` | 13,314,159 | `834ac58385d0e8459cbb29c7d933044fb9cb2301704c2a8369c8002f3097e26b` |

Release APK: `com.example.notes`, versionCode 1, `1.0`, minSdk 24, targetSdk 36, compileSdk 37, launchable
`MainActivity`, not debuggable, zipalign check OK, **unsigned** (`apksigner verify`: DOES NOT VERIFY, missing
META-INF/MANIFEST.MF). Release AAB: `BundleConfig.pb`, one base module (manifest, two dex files, resources, four ABI
libraries), **unsigned** (`jarsigner -verify`: no manifest). Warnings in all logs: only "Unable to strip ...
libandroidx.graphics.path.so" (no NDK in the image; see Limitations). Throwaway copies of the first project (one with the
block form of `compileSdk`, one with BOM 2026.09.00 and a plain `compileSdk = 37`) had also built before the template
was changed. The Dockerfile, image and volumes stay outside the repository.

What the template tests cover: valid and invalid package names (including every Kotlin hard keyword and Java reserved
word, Windows device names, leading/trailing/double dots, uppercase, non-ASCII, control characters), application IDs,
project names (injection characters, bidi and zero-width characters, combining marks, NFC normalisation), SDK-level
and version-code rules, strict integer typing, derived identifiers, escaping of `&`, `'`, `<`, quotes, backslashes and
a leading `@` / `?` in `strings.xml`, single-pass placeholder substitution, unsafe and non-canonical paths (traversal
through a placeholder value included), determinism (rebuilt config, reordered template files, no dates or host
names), exactly the 19 expected files, package declaration equal to directory, imports used and sorted, catalog
consistency (every accessor exists, every entry is used, Compose libraries take their version from the BOM), manifest
(launcher, `exported`, no permissions, resources exist), well-formed XML for varied names, the Compose skeleton, and
`PatchSet` compatibility: preview, apply to a real workspace (byte-for-byte), refusal over existing files,
rollback, checkpoint, and `review_patch`.

Static review compatibility: the rendered project has **no review finding** (14 files analysed, none unparsed) for the
default config and for six varied configs (other package, separate application ID, a name with `&`, a Devanagari
name, other SDK levels). That is only meaningful if the rules are alive on this project, so seven sentinels break one
generated file and require the right rule to fire: `import.missing`, `resource.unresolved` (twice),
`manifest.class_missing`, `manifest.exported_missing`, `syntax.unbalanced_brackets` and `import.unresolved_project`.
No review rule was changed or weakened. Two further breakages that were tried are **not** caught by the existing
review rules, and were left alone: a manifest `@style/` reference to a style that does not exist, and an
`app/build.gradle.kts` without `namespace`. The template tests check both directly instead, for six configs: the
module has exactly one `namespace`, inside the `android` block, equal to the package and a valid package name, and it
is what `.MainActivity`, the package declarations and the `R` import resolve against; every `@type/name` reference in the
manifest and in the resource files, and every project-defined `parent` style, resolves to a resource defined in the
default `values` directory (not only in `values-night`). The checker itself is tested against deliberately broken copies.

The `compileSdk` work adds tests for: API 37.1 rendered in the Gradle file and not hard-coded (a widened range renders
37.2), invalid minor levels (0, 2, 99, negative, other API levels, non-integers and booleans), the pair compared as
(API, minor), `targetSdk` compared with the API level only, configs and dumps written before the minor field (still valid),
the review reading the block (multi-line, one-line, Kotlin and Groovy DSL, spacing variants, nested braces, line numbers,
comments and strings ignored, `preview(...)`, variables, arithmetic and unclosed blocks unknown without a crash),
`gradle.sdk_order` on the block (target above compile, min above target, an equal target under 37.1 in order, unreadable
block silent, warnings not blocking), `change.sdk_changed` (lowered API level, 37.1 to 37.0, whole number to block), and the
rendered project's own SDK levels read back by the review.

The Compose Preview fix adds regression tests for: `testOptions { unitTests { isIncludeAndroidResources = true } }`
inside the `android` block; the `androidComponents` block using the AGP 9 host-test API for every variant (no variant
singled out, and the removed `enableUnitTest` absent); the `HostTestBuilder` import once, on the first line, before
`plugins`; the order of the four top-level blocks; balanced braces, parentheses and brackets in every Gradle script; **no
generated unit-test source or test dependency**; and that nothing else about the module changed (release still not
shrunk, no signing configuration, flavors or extra build type). The rendered project still has no review finding.

Not done for 5.1: fault injection into the five real projects (the real-project run above is a before-and-after
comparison of unmodified projects); the contracts, worker and CI suites (nothing there was touched). `pyproject.toml`
gained one `E501` per-file ignore for `templates/kotlin_compose.py`, because a TOML inline table of the version catalog
cannot be wrapped.

### Phase 5.2 verification (multi-screen projects; `p3/phase5-screens`, based on `p3/phase5-templates` at `f008772`)

| Check | Result |
|---|---|
| Windows 10, Python 3.12.10: `pytest packages/agent-core/codegen` | 1689 passed, 5 skipped, 1 xfailed (the 1503 / 5 / 1 of `f008772` plus 186 new tests) |
| Linux (WSL Ubuntu, Python 3.14.4, ext4), same suite from a fresh export of the working tree | 1693 passed, 1 skipped, 1 xfailed |
| `ruff check`, `ruff format --check`, `compileall` | clean on both platforms |
| New tests | 186: `ProjectSpec` and `ScreenSpec` 102, generation and integration 83, plus 1 for the error messages of the package and application-ID validation |
| Phase 5.1 preserved | the 5.1 test files pass unchanged, and without a spec the output hashes (SHA-256) of three configs equal the values taken from the 5.1 renderer before 5.2 changed it |
| Mutation testing of the new code | 64 of 64 caught. The first run caught 61: one survivor was a redundant validator (removed), one an unasserted message of the new code, one an unasserted message in 5.1's package and application-ID validation (a small gap in the 5.1 tests, now covered) |
| Static review of the generated projects | no finding for 5 specs (1, 3, 4 keyword-named, 12 screens, a cycle with a chosen start) x 3 configs (default, other package and application ID, special project name); eight deliberate breakages are each caught by the right rule (`navigation.destination_missing`, `navigation.start_destination_missing`, `navigation.duplicate_destination`, `import.missing`, `import.unresolved_project`, `resource.unresolved`, `syntax.unbalanced_brackets`) |
| **Gradle builds of four sample projects** | **all 28 commands exit 0** (below) |

**Gradle builds (Docker, 2026-11-20, the image and volumes of 5.1's validation).** JDK 17 (Temurin 17.0.21), system Gradle
9.6.0, AGP 9.5.1, Kotlin 2.4.21, Compose BOM 2026.11.01, SDK platform 37.1, build-tools 36.0.0. Each sample was rendered
through `PatchEngine` (after `review_patch`, which found nothing) into an empty workspace, copied into the container and
built with `G` = `gradle --no-daemon --console=plain --stacktrace --warning-mode all`. The final tree renders exactly the
files that were built (byte-identical, checked).

| Sample | Spec and config | Files | `G build` (cold) |
|---|---|---|---|
| `one` | 1 screen (`Home`), default config | 19 | 105 tasks, 1m38s |
| `three` | `Home` opens `Settings` and `About`, `Settings` opens `About`; titles with `&` and `'` | 21 | 105 tasks, 1m09s |
| `keywords` | `Class`, `Object`, `Fun`, `Val` (keywords in lower case), 4 screens | 22 | 105 tasks, 1m23s |
| `twelve-full` | 12 screens, the maximum of 8 buttons on the first; package `org.acme.deep.pkg`, application ID `com.acme.NotesPro`, name `R&D Tracker`, versionCode 3, `2.1` | 30 | 105 tasks, 1m19s |

For every sample, each of these exited 0: `G build` (cold), `G tasks --all`, `G assembleRelease`, `G bundleRelease`, `G lint`,
`G :app:lintRelease` and `G test`. Lint: **0 errors and the same four warnings as Phase 5.1 on every sample**
(`OldTargetApi`, `AndroidGradlePluginVersion`, `DataExtractionRules`, `MissingApplicationIcon`): the generated strings produce
no unused-resource or other new warning. `test` runs `testDebugUnitTest` and `testReleaseUnitTest` with `NO-SOURCE`: there are
no unit tests. The only warning in any log is "Unable to strip ... libandroidx.graphics.path.so" (no NDK in the image).

| Sample | Release APK (unsigned) | Release AAB (unsigned) | Debug APK |
|---|---|---|---|
| `one` | 9,340,694 B, `e0fd0c06088fdbd41127a252292c0fe5bb0f0680342463188b11d36fafdc39a9` | 8,959,516 B, `2fe746636249fefe2da119dd8ec65d5d8279a0fe6e4654ceb69c5fffc45feac4` | 13,314,135 B |
| `three` | 9,342,734 B, `ef9bcb1ccf79ef2bdc28f83dc99eecd543fb64d76d5d41aa179fec1cbf091d29` | 8,967,701 B, `70949f5c477ccbd6d8f3fcbef8aa330dbdf0656a76a0581a62912039b89efb30` | 13,332,559 B |
| `keywords` | 9,358,670 B, `a3ba09ba01ea70317de9a69b5a1941ca98ff351630a9e1da5a4dda53c6bc0271` | 8,969,642 B, `21a9d2dd1f12b53ae37757ac84a0d79b1445abfe52a0ceed557e5856e65df28c` | 13,332,115 B |
| `twelve-full` | 9,378,298 B, `b4bcf928ddd19b248f965bb0c74e8d8533aba3b29472b8adc23aaa1ab606e29d` | 8,992,540 B, `d05c171ed3be7363395cbb6f935ba745a597c63addef8313efcfdab9ea5edc76` | 13,368,127 B |

All four: minSdk 24, targetSdk 36, compileSdk 37, launchable `MainActivity`, release APK not debuggable (debug APK
debuggable), zipalign check OK, release APK and AAB **unsigned** (`apksigner` DOES NOT VERIFY, `jarsigner` finds no manifest).
`twelve-full` shows the namespace and application ID apart: package `com.acme.NotesPro`, versionCode 3, versionName `2.1`,
label `R&D Tracker`, launcher `org.acme.deep.pkg.MainActivity`. **Not verified when these builds were made**: any run on an
emulator or device (navigation at runtime, the previews), signing, other SDK levels, the Gradle wrapper, any unit test (none
existed). Afterwards the `three` sample was run on an emulator (next section) and Phase 5.3 added the navigation tests.

What the 5.2 tests cover: valid and invalid screen names (case, digits, non-ASCII, separators, length, the `Screen` suffix),
route and constant derivation, titles and descriptions (injection characters, bidi, double spaces, length, NFC), edges (unknown,
self, duplicate, too many), start screens, the 12-screen limit, unreachable screens, cycles, immutability and JSON round trips;
the exact file set and the byte-identity of every file that should not change; package declarations, imports used, sorted and
unique; button and `onBack` wiring; `Routes` as `const val`; every `navigate` target declared; the start destination; the
review's own navigation facts; strings (what is used is defined and nothing else, escaped, parse-back); determinism; the patch
limits; refusal of a template without spec support, of a missing base file and of a screen overwriting a file; `PatchSet`
preview, byte-for-byte apply, rollback, refusal over an existing project, checkpoint and `review_patch`.

### Phase 5.2 sample on an emulator (runtime check, 2026-11-20)

Phase 5.2's builds were never run until the user approved installing and driving the three-screen sample on their running
emulator (replacing the earlier `com.example.notes` install). No repository file was changed for it.

| | |
|---|---|
| Device | `emulator-5554`, AVD `Medium_Phone_API_37.0`, Android 17 (API 37.0), x86_64, 1080 x 2400 |
| App | the Docker-built **debug APK of the Phase 5.2 `three` sample** (13,332,559 B, SHA-256 `ea72b96a05a81f69bce875da301235c14cabf0e12022dac8d76eb15bfa1aa187`), i.e. the build listed above, **not** the Phase 5.3 one (it differs only by `AppNavHost`'s optional parameter); installed with `adb install -r`, launched in 2.5 s |
| Result | **20 of 20 checks passed** |

Checked on the device (each with a screenshot and a UI-hierarchy dump): Home shows both buttons and no Back; Settings shows
its button and Back; About shows its text and Back; the in-app Back and the system Back each return one screen; Home to About
directly and Back returns to **Home**, not to Settings; Home, Settings, About and the system Back twice returns to Settings and
then Home; rotating to landscape keeps Settings, About is reachable in landscape, and rotating back keeps About; the system Back
on Home leaves the app; relaunching starts at Home. Logcat (25,307 lines, 354 about the app): no `FATAL EXCEPTION`, no
`AndroidRuntime` error, no ANR, no process death, no native crash. Its one error-level line that mentions the app is
`system_server` (`WindowOrganizerController`: "Attempting to externally change a non-organized container") logged while the
task was closed after Back on Home; it is the platform's, not the app's. The rotation settings were restored afterwards.

**Not covered**: dark mode, the Compose previews in an IDE, other samples, other devices and API levels, an install of a signed
build. The debug key is Docker's, so Android Studio's own install of the same package needs an uninstall first.

### Phase 5.3 verification (generated navigation tests; `p3/phase5-nav-tests`, based on `p3/phase5-screens` at `f6c07c0`)

| Check | Result |
|---|---|
| Windows 10, Python 3.12.10: `pytest packages/agent-core/codegen` | 1824 passed, 5 skipped, 1 xfailed (the 1689 / 5 / 1 of `f6c07c0` plus 135 new tests) |
| Linux (WSL Ubuntu, Python 3.14.4, ext4), same suite from a fresh export of the working tree | 1828 passed, 1 skipped, 1 xfailed (the 1693 / 1 / 1 of `f6c07c0` plus 135) |
| `ruff check`, `ruff format --check`, `compileall` | clean on both platforms |
| New tests | 135, all in `test_templates_navtests.py`; 7 existing tests of `test_templates_screens.py` were updated for the new file set (counts, the test path, and the two build files, which are no longer in the "byte-identical" list because the new tests pin exactly what was added to them) |
| Phase 5.1 and 5.2 preserved | all their tests pass; without a spec the output hashes of the three 5.1 configs are unchanged; with a spec only `AppNavHost.kt`, `strings.xml`, the catalog, `app/build.gradle.kts` and the new test differ from 5.2 (a test lists them) |
| Mutation testing of the new code (Python) | **76 of 76 caught** (dependency lines, versions and configurations, the release skip, the class text, button order and occurrence counting, the way into screens, test names, the support check, the refusals, the layer order). The first run caught 73: it found that no test pinned breadth-first against depth-first search (a spec with a shortcut was added), none covered a test name colliding with a helper's, and none the order of the two generator layers; and one mutant (a missing `seen` check) made the generator loop forever, so it hung for 17 minutes until stopped. The harness now has a 180 s limit, under which that mutant is reported as a hang (detected, but only as a timeout: the loop cannot be asserted from inside a test) |
| Mutation testing of the generated app (Kotlin, in Docker) | **14 of 14 caught**, none by a compile error (below) |
| Static review of generated projects | no finding for 9 specs (1, 3, 4 keyword-named, 12 screens, a cycle with a chosen start, equal titles with a screen called "Back", colliding function names, a helper-name collision, a shortcut graph) x 3 configs, and none in the four built samples (`review_patch` before they were applied); a broken test file is caught (`syntax.unbalanced_brackets`) |
| **Gradle builds of the four samples** | **all 28 commands exit 0**; the navigation tests pass on the debug unit-test task (below) |

**Gradle builds (Docker, 2026-11-20, same image and volumes as 5.1 and 5.2).** JDK 17 (Temurin 17.0.21), system Gradle 9.6.0,
AGP 9.5.1, Kotlin 2.4.21, Compose BOM 2026.11.01, SDK platform 37.1, build-tools 36.0.0, plus (new) Robolectric 4.18.1, JUnit
4.13.2, navigation-testing 2.10.2 and the BOM's ui-test 1.13.0. Each sample was rendered through `PatchEngine` (after
`review_patch`), copied into the container and built with `G` = `gradle --no-daemon --console=plain --stacktrace
--warning-mode all`. The tree renders exactly the files that were built (byte-identical; the SHA-256 values are pinned in a test).

| Sample | Files | `G build` | Navigation tests (`testDebugUnitTest`) |
|---|---|---|---|
| `one` (1 screen) | 20 | 110 tasks, 1m26s | 2 passed |
| `three` (the 5.2 sample, `Home` to `Settings` and `About`, `Settings` to `About`) | 22 | 110 tasks, 1m39s (from a clean directory) | 7 passed |
| `keywords` (`Class`, `Object`, `Fun`, `Val`) | 23 | 110 tasks, 1m28s | 8 passed |
| `twelve-full` (12 screens, 8 buttons on the first, other package, application ID, name and version) | 31 | 110 tasks, 1m45s | 40 passed |

For every sample, each of these exited 0: `G build` (which runs the debug tests), `G tasks --all`, `G assembleRelease`,
`G bundleRelease`, `G lint`, `G :app:lintRelease` and `G :app:testDebugUnitTest --rerun :app:testReleaseUnitTest --rerun`
(`testReleaseUnitTest` is SKIPPED, see finding 2). **Lint: 0 errors and the same four warnings as before, on every sample**
(the test code and its dependencies add none). The only warning in any log is "Unable to strip ... libandroidx.graphics.path.so"
(no NDK in the image). Unit-test results: 0 failures, 0 errors, 0 skipped tests in each debug run.

| Sample | Release APK (unsigned) | Release AAB (unsigned) | Debug APK |
|---|---|---|---|
| `one` | 9,340,694 B, `9680c000cfe0bc20d6c332c513779c71cdc91f6e484d9c8c6b00ebcd3d36714d` | 8,959,635 B, `23aa207c219c7f5c2c2f94268c8e950e344842e6b9a511394239c6d1031c12b4` | 13,314,378 B |
| `three` | 9,342,734 B, `b043b108d223274f5b6b4e52fd400e5ae24b8ba3d2e32e7cec87af9995acf5e7` | 8,967,736 B, `e49bd4e2e98a6aeb73b3403a16851c322c53dba7129c6c8acec8d7c88de9ff20` | 13,332,802 B |
| `keywords` | 9,358,670 B, `65665a7c2432c04c57cdffe62e4c6ed4676a015200d36420d5786ac65c719b06` | 8,969,583 B, `5922b1f29eeed449e75b80938a18312ab480b7c58887187b45c6ac0cdea481a1` | 13,332,358 B |
| `twelve-full` | 9,378,298 B, `311e9576b3a005b70e5fcdf5acc62ed1e40f0be643c0bfd89817aca6be6892a8` | 8,992,587 B, `b2445836bb96e0a778723f5eed825a08799fb3a409ae3286b72d2abe60571f2d` | 13,368,362 B |

All four: minSdk 24, targetSdk 36, compileSdk 37, launchable `MainActivity`, release APK not debuggable (debug APK debuggable),
zipalign OK, release APK and AAB **unsigned** (`apksigner` DOES NOT VERIFY, `jarsigner` finds no manifest). **No test library
reaches a release output**: the release APK has no Robolectric, JUnit, navigation-testing or Compose-test class and no
`ComponentActivity` in its manifest; only the **debug APK** carries `ui-test-manifest`'s extra activity. A comparison of the `three`
sample with and without the test file and dependencies (both built from clean): the **release APKs are byte-identical**
(same SHA-256); the two AABs contain the same 128 entries with identical names, sizes and CRC-32 values but list some
`META-INF/*.version` entries in a different order, so their hashes differ (an AAB is reproducible for one project: two clean
rebuilds gave one hash). The sizes of the release APKs equal those of Phase 5.2 for every sample, while their hashes differ,
because `AppNavHost`'s default parameter changes its bytecode.

**Findings that changed the design** (details under "Generated navigation tests (Phase 5.3)"): (1) the first run failed with
"Android SDK 36 requires Java 21 (have Java 17)", fixed without changing a version by pinning API 35 in the test; a project
with `minSdk` 36 failed every test in `ShadowPackageParser` with that fix, so it gets no test; (2) `testReleaseUnitTest` failed 7
of 7 ("Unable to resolve activity": `ui-test-manifest` is debug-only) while `testDebugUnitTest` passed, and
`testImplementation(ui-test-manifest)` failed both, so the release task is skipped (checked afterwards: `tasks --all` and the
release Compose Preview run-files task still pass); (3) `createAndroidComposeRule` is deprecated in Compose 1.13.0, so the `v2`
rule is used; (4) the plan's note that the BOM does not manage `ui-test-*` was wrong, so they are declared without a version.

**The tall test screen is needed.** With Robolectric's default (small) screen, the 12-screen sample fails 15 of its 40 tests
(for example "expected:<step8> but was:<step0>": after the click, the app was still on the first screen). The likely cause, not
inspected further, is that the first screen's 8 buttons and title do not fit and the generated screens are a plain `Column` that
does not scroll. The tests therefore run at 411 x 914 dp. If that is the cause, it is a limitation of the 5.2 screens (small phone
or landscape) that 5.3 found and left alone.

**Mutation testing of the generated app (Kotlin, Docker).** Fourteen deliberate breakages of the generated three-screen app
were each applied to a copy and `testDebugUnitTest` run: the unmodified copy passes 7 of 7; **all 14 mutants made tests fail,
none by a compile error** (the failing tests are named in the log), and the restored copy passes 7 of 7 again. They are: Home opens the
wrong screen; Settings opens Home instead of About; Settings' Back not wired; About's Back pushes Home; About's Back pops to Home;
Settings' Back pops twice; the start destination is Settings; the About destination is registered under another route; Settings'
Back button opens About; Settings swallows the system Back; Settings has an extra button; Home lost its About button; Home lost
its description; About shows another screen's title.

What the Python tests cover (new): the five dependencies and their versions in the catalog and the build file, and nowhere else;
that no test library can reach a release build; the skip of the release task; the test's path, package, runner, SDK, rule and
theme; that no text is written into Kotlin (resource ids only); a well-formed class for nine specs (imports sorted and used,
brackets, line length, unique valid function names); one test per start, back and screen and per edge; the way into each screen
being a shortest one; equal texts, a screen called "Back", an edge into the start screen and colliding names; **a simulator that
runs the generated script against a model of the app built independently from the spec** (it passes on the model and fails when a
button opens the wrong screen, Back does nothing, Back goes to the start or the system Back does nothing); the unsupported minimum
SDK; refusals when an anchor is missing, repeated or a file is absent; that the screens are applied before the tests are added;
`AppNavHost`'s signature and `MainActivity` unchanged; the review's navigation facts; determinism; the patch limits; and the pins
of the four built projects.

### Phase 5.4 verification (scrolling screens; `p3/phase5-scroll-signing`, based on `p3/phase5-nav-tests` at `aac94e1`)

| Check | Result |
|---|---|
| Windows 10, Python 3.12.10: `pytest packages/agent-core/codegen` | 1832 passed, 5 skipped, 1 xfailed (the 1824 / 5 / 1 of `aac94e1` plus 8 net new tests) |
| Linux (WSL Ubuntu, Python 3.14.4, ext4), same suite from a fresh export of the working tree | 1836 passed, 1 skipped, 1 xfailed (the 1828 / 1 / 1 of `aac94e1` plus 8) |
| `ruff check`, `ruff format --check`, `compileall` | clean on both platforms |
| Mutation testing (Python) | **88 of 88 caught**: 17 new mutants (scroll removed, moved before or after the right padding, horizontal instead of vertical, imports dropped, centring lost, `fillMaxSize` dropped; the test not scrolling before click or title check, its import dropped, the tall screen back; the activity registration removed, ordered after the Compose rule, for the wrong class, or its imports dropped), plus the Phase 5.3 set re-run on the new code, **71 of 71** (it had 76: five mutants of code that no longer exists, the tall-screen qualifier and the release-task skip, were removed). One of the 71 makes the generator loop forever and is detected only by the harness's 180 s timeout. No mutant survived |
| Mutation testing of the generated app (Kotlin, Docker) | **16 of 16 caught**, none by a compile error: the 14 of Phase 5.3 plus "Home does not scroll" and "Settings does not scroll" (`performScrollTo` fails without a scroll container); the unmodified copy passes 7 of 7 before and after |
| Static review of the generated projects | no finding in the 9 specs x 3 configs of 5.3 and none in the four built samples (`review_patch` before they were applied) |
| **Gradle builds of the four samples, each from an empty build directory** | **all 28 commands exit 0**; the navigation tests pass on the debug **and the release** unit-test task |

**Gradle builds (Docker, 2026-11-21, the same image and volumes).** JDK 17, system Gradle 9.6.0, AGP 9.5.1, Kotlin 2.4.21, Compose BOM
2026.11.01, SDK platform 37.1; the same seven commands as in 5.3 (`G build`, `tasks --all`, `assembleRelease`, `bundleRelease`,
`lint`, `:app:lintRelease`, and `:app:testDebugUnitTest --rerun :app:testReleaseUnitTest --rerun`). Every sample is the project the
pinned SHA-256 of `test_templates_navtests.py` describes (source digests re-computed in the container and equal).

| Sample | Files | `G build` | Navigation tests: debug / release (default Robolectric screen) |
|---|---|---|---|
| `one` | 20 | 111 tasks, 1m17s | 2 / 2 passed |
| `three` | 22 | 111 tasks, 1m32s | 7 / 7 passed |
| `keywords` | 23 | 111 tasks, 1m15s | 8 / 8 passed |
| `twelve-full` | 31 | 111 tasks, 2m57s | **40 / 40 passed** (15 of 40 failed on this screen in 5.3 without scrolling) |

Lint: **0 errors and 5 warnings** on every sample (see the Phase 5.4 limitations: the fifth is the AGP 9.5.2 notice). The only
warning in any log besides lint is "Unable to strip ... libandroidx.graphics.path.so" (no NDK in the image).

| Sample | Release APK (unsigned) | Release AAB (unsigned) | Debug APK |
|---|---|---|---|
| `one` | 9,340,694 B, `f6efea2ff6d39cf42cc824baa4f37d8985f0121032642bfe8ff5bff01e6fd493` | 8,959,616 B, `f61ffcafcaa857fb1757b85af3da62b59dc2defc2905912750c299724b79ecd2` | 13,314,378 B |
| `three` | 9,342,734 B, `519c39ef62e232e1c6e6640876c16b5b6f3fd309f5b520fc0a36fcd503da870d` | 8,967,812 B, `6f1ef5c7cce5784622c4cac7ea7eaecfe0d2382b7064dc1265efa2bde035d3e9` | 13,332,802 B |
| `keywords` | 9,358,670 B, `7eceabe72288422f8e08ff9b6a587695200b6fb600f3f763e11d3a8cf7638e32` | 8,969,551 B, `6542747505119fad4da41979db36812082efee077647d0c71277aa539d7fa85f` | 13,332,358 B |
| `twelve-full` | 9,378,298 B, `d3ea871703a24849858eb3b9fbab9a4d919b2648067a5abf4cf98a9e802d6417` | 8,992,708 B, `b3d1064a28daf5c064ba292c2266946e9d385ca64239929e79e759212e4bfc80` | 13,368,362 B |

All four: minSdk 24, targetSdk 36, compileSdk 37, release APK not debuggable, zipalign OK, outputs **unsigned**, no test library in
any release APK and no `ComponentActivity` in its manifest (only the debug APK carries `ui-test-manifest`'s). The release APKs have
the same sizes as in 5.3 and different hashes, as the screens changed.

**Emulator, before and after (Pixel 8 emulator, Android 17, API 37.0).** The 12-screen sample's debug APK built before the fix
(the 5.3 build, `e014cacb94a9...`) and after it (`aeec18e69b98...`, the build above) were installed in turn with `adb` and driven
with `uiautomator`: open the first screen (8 buttons), scroll until the button "Step 8" is fully visible, tap it, check the
"Step 8" screen, press Back. The emulator's size, density, font scale, night mode and rotation were set per condition and
**restored afterwards** (size 1080x2400, density 420, rotation 0, night mode off, as found). No `FATAL EXCEPTION` in any run.

| Condition | Before the fix | After the fix |
|---|---|---|
| Portrait 1080x2400 | Step 8 visible, works | works |
| Small portrait 720x1280 at 320 dpi (360 x 640 dp) | works, all 8 fit | works |
| Small portrait, dark mode | works | works, readable (screenshot checked) |
| Small portrait, font scale 1.5 | works, all 8 fit | works |
| **Landscape 1280x720 (640 x 360 dp)** | **Step 8 never reachable** (cut off after Step 3 or 4, scrolling does nothing) | **reachable after 2 swipes**, opens, Back returns |
| **Landscape 2400x1080, dark mode** | **never reachable** (Step 4 and a sliver of 5) | **reachable after 1 swipe**, opens, Back returns |

So the defect only appears when the screen is short, i.e. in landscape; 360 x 640 dp portrait still fits eight buttons. In every
reachable case the "Step 8" screen opened and Back returned to the first screen. Screenshots and `results.json` are kept in the
validation scratch directory, not in the repository. **Not run**: the Compose previews in Android Studio, a physical device, other API
levels, other samples. The Medium Phone emulator was not running at the time (it had stopped during the first attempt, under memory
pressure from Docker and two emulators), so the Pixel 8 emulator was used.

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
- **Ten rule groups run** (`syntax`, `imports`, `resources`, `gradle`, `manifest`, `navigation`, `deeplinks`,
  `security`, `auth` and, with a "before" state, `changes`; 69 rule ids). Nothing checks incorrect API use or null
  safety yet (4b-3), and there is no language or framework detector. The security and authentication groups are the
  narrow sets listed under Phases 4b-2b and 4b-2c, not an audit.
- A review report with no findings therefore says nothing about API use, little about security and authentication,
  and nothing about whether an app's authorization model is sound. It must not be presented as "the project is safe".

Phase 4b-1 (manifest, build and change-aware rules):

- **Recall is deliberately limited by readability.** `gradle.dependency_missing` and `manifest.permission_missing`
  need a module's whole dependency list, so they are silent for any module that applies a convention plugin or
  has a dependency call that cannot be parsed. `manifest.permission_missing` further needs *every* module to be
  readable, so on real multi-module projects it usually does not fire (it was silent on all five clones).
  `manifest.exported_missing` needs a resolvable `targetSdk` (see "Target SDK resolution": a number, a catalog
  version or a `buildSrc` constant) and `gradle.compose_plugin_missing` a literal Kotlin version; a convention plugin
  or a shared script silences them (the target stays unresolved in 2 of 5 clones, the Kotlin version in 3). Readable
  single-module projects, which is what generation produces, get the full set.
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

- **The call-site rules need a target SDK the build states plainly.** When 4b-2b was committed only
  `platform-samples` (of five) wrote `targetSdk` as a number, so these rules were silent on the rest; the follow-up
  under "Target SDK resolution" now also reads a catalog version and a `buildSrc` constant, which covers `sunflower`
  and `iosched`. They stay silent where the target is still unknown: `AntennaPod`'s app module (shared script),
  `nowinandroid` (convention plugins) and any computed expression.
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

Phase 4b-2c (authentication):

- **Authentication correctness is not checked.** The rules never ask whether tokens are validated, whether a screen is
  guarded, or whether sign-in works; they cover configuration, secrets and storage only.
- **The dependency rules are silent on most real projects.** `auth.credential_manager_provider_missing` needs every
  module of the build readable, and `auth.appauth_redirect_not_configured` needs the application module and
  everything it depends on readable. Of the five real projects only one application module (`AntennaPod`'s
  `app-wearos`) qualifies: `iosched` and `sunflower` declare dependencies in `allprojects` / `subprojects`,
  `platform-samples`' and `AntennaPod`'s `app` depend on modules that use constants or shared scripts, and
  `nowinandroid` uses convention plugins. Readable single-module projects (what generation produces) get the rules.
- **The provider coordinates were only partly checked against documentation.** `firebase-auth`,
  `androidx.credentials:credentials` (+ `credentials-play-services-auth`) and `net.openid:appauth` come from their
  setup pages. The coordinates for FirebaseUI, legacy Google Sign-In, `googleid` and Auth0 were not fetched, so a
  library that bundles one of them under another coordinate is invisible to `change.auth_dependency_removed_still_used`
  (it errs towards silence: a coordinate that starts with a listed prefix counts as providing the classes, so a
  removal replaced by a lookalike is also silent). Imports count as "call sites": an unused import is a use.
- **Only some files are read.** The review loader reads `.kt`, `.kts`, `.java`, `.xml`, `.gradle`, `.toml` and
  `.proto`; a private key or secret in a `.pem`, `.json`, `.properties`, `.txt` or `.md` file (including
  `google-services.json` and `keystore.properties`) is never seen, and a keystore is binary. Secrets in comments are
  reported; secrets in test source sets are not.
- **Secret detection is a heuristic for a few shapes.** Distinctive token formats and `*secret*`-named literals only.
  A password assigned to a variable called `password`, an API key named `apiKey`, a bearer token in a header
  constant, a secret split across two literals or assembled at run time are not found. `AIza...` keys and JWTs are
  skipped by choice (Firebase and Maps keys ship inside apps, example JWTs are common), although the security tips say
  "never commit API keys"; that choice was made for noise, not verified against Firebase documentation. A secret that
  happens to contain `test`, `sample` and similar words is treated as a placeholder.
- **Preference storage is an advisory about explicit keys.** Only the ten key names listed, written as string literals
  through an editor in a file without encrypted storage; `DataStore`, `putString(KEY_CONSTANT, ...)`, a token under
  the key `token`, and `Bundle`/`Intent` extras are not judged. Any mention of `KeyStore`, `Cipher` or `encrypt`
  anywhere in the file silences it, even for an unrelated value.
- **Redirect checks need literals.** `auth.appauth_redirect_scheme_unmatched` reads `Uri.parse("scheme:/path")` and
  `"scheme:/path".toUri()` as the fourth argument of `AuthorizationRequest.Builder` or as the argument of
  `setRedirectUri`; an `https` App Link redirect is compared on its scheme only (its host, path and Digital Asset
  Links are not checked), and scheme case is ignored although Android may not treat schemes case-insensitively.
- Nothing in 4b-2c was compiled or run on a device.

- **No known false positive of the 4a rules remains on the five validation projects** (Phases 4a.6 and 4a.7
  fixed the last four). Two limits stay by design:
  - `items(total) { ... }` in a lazy list is judged as the extension that needs its import, because `total` may be
    an `Int` or a list and the call does not say which. Only a named `count =`, an integer literal, or a `.size` /
    `.itemCount` argument selects the member.
  - A wildcard import provides a framework class only if the catalog lists that class. Eight names that exist both as
    Compose or library types and as framework classes are listed (`Surface`, `Color`, `Canvas`, `Path`, `Icon`,
    `Image`, `RadioButton`, `Snackbar`); another such name used with a wildcard import of its framework package would
    still be reported until it is added. The probe that found these checked twenty well-known names, not every class.

Phase 5.1 (project templates): see "Project templates (Phase 5.1)" above. In short: the default project's debug build,
release build, AAB, `lint` (0 errors, 4 warnings) and `tasks --all` pass with Gradle, after two failures that changed
the template (compileSdk 37.0 needed API 37.1; AGP's Compose Preview tasks needed Android resources and unit tests
enabled for every variant). The release APK and AAB are **unsigned**; **the default project has no application unit
test**; the four lint warnings are known limitations; only the default configuration was built (no emulator, no other package or SDK
level, no Gradle wrapper); there is one template (Kotlin + Compose, one module); the wrapper jar and scripts are not
generated; and two kinds of breakage in a generated project are not caught by the review (they are covered by the
template tests instead).

Phase 5.2 (multi-screen projects): see "Multi-screen projects from a `ProjectSpec`" above. In short: the screens are
static (title, description, buttons; no state, input or arguments), at most 12 screens and 8 buttons each, routes are
derived and not chosen, and only the Kotlin + Compose template supports a spec. Four sample specs built with the same
Gradle commands as 5.1; the three-screen sample was run **once, on one Android 17 emulator** (navigation, Back, rotation,
logcat), the other samples and the previews were not run; the outputs are unsigned. The static review cannot see a removed
`Routes` constant (the route becomes "computed"); the Gradle build catches that. Nothing consumes a `ProjectSpec` yet.

Phase 5.3 (generated navigation tests): see "Generated navigation tests (Phase 5.3)" above. In short: a project with a spec
gets a Robolectric + Compose-test `NavigationTest` and five test-only dependencies; it passes on the debug unit-test task of
four sample specs and fails when the generated navigation is broken. It simulates **API 35 on JDK 17** (Robolectric 4.18.1
needs Java 21 for API 36), so a project with `minSdk` above 35 gets no test; there is no instrumented test; the default
project (no spec) is unchanged and has no test. Phase 5.3 skipped the release unit-test task and hid the missing scrolling behind a
tall test screen; **Phase 5.4 fixed both** (scrolling screens, activity registration in the test).

Phase 5.4 (scrolling, release tests, signing): see "Scrolling screens, release tests and signing (Phase 5.4)" above. In short: the
generated screens scroll and the tests check it; the navigation tests run on the debug and release tasks; signing was tried only
with a throwaway key (an optional `keystore.properties` block works, nothing is generated); **the Compose previews are still
unverified**, and the emulator checks cover one emulator, one sample and a few sizes.

## Unfinished integration work

Not done:

- **Phase 4b-3** (API-use and null-safety rules).
- **More builds of the Phase 5.1 and 5.2 templates.** Debug, release, bundle, `lint` and `tasks --all` of the default
  project (5.1) and of four sample specs (5.2) were run (in a temporary Docker image kept outside the repository). Still to
  do: signing the release outputs, more emulator or device runs (only the three-screen sample ran, once; the previews never),
  other SDK levels, a build with the Gradle wrapper, instrumented tests (they need an emulator), and unit tests for logic
  beyond navigation once generated code has some. That belongs in the `android-build` image, which needs a JDK and the
  Android SDK (platform 37.1, build-tools 36.0.0, ideally the NDK): Person 4's environment.
- **Producing a `ProjectSpec`.** Nothing builds one yet. Mapping a planner's output (`ImplementationPlan`, whose shape is
  Person 2's) onto it, and the contracts' `AndroidTarget` onto `ProjectConfig`, is adapter work that waits for the v0.2
  contract proposal to be reviewed and for the LLM provider decision.
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
