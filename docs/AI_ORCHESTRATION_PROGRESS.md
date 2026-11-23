# AI Orchestration Progress (Person 2)

Owner: Person 2. Code: `packages/agent-core/orchestration` (`androai_orchestration_core`) and `workers/orchestration` (`androai_orchestration`, Celery glue).

## Status

| Module | State | Verified |
|---|---|---|
| Provider abstraction (config, routing, retry, fallback, budgets, structured output, redaction) | Done | 18 unit tests (providers, planning rules, DAG validation) with a scripted fake provider |
| Anthropic / OpenAI-compatible adapters | Written | **Not run against a real API** (no keys, SDKs not installed here) |
| Project intelligence (analyzer, scoped BM25 index, incremental update, retrieval) | Done | 6 tests on a fixture project |
| Requirement understanding, architecture, decomposition, modification/impact planning, failure classification, repair planning | Done | Via workflow tests; LLM output is scripted |
| LangGraph workflows: new app, modify, repair | Done | 26 tests with in-memory SQLite + MemorySaver |
| Persistence (`RunStore`, `orch_*` tables) | Done | SQLite only; **not run on PostgreSQL**, **no Alembic migration yet** |
| PostgreSQL LangGraph checkpointer (`make_checkpointer(url)`) | Written | **Not run** (no PostgreSQL available) |
| Redis run lock, Celery tasks | Written | Task registration verified; **never run against Redis/a broker** |
| Workflow recovery | Done | Tested: restart mid-wait, crashed `running` run, lost result wake-up |

Total: 51 tests passing (`pytest packages/agent-core/orchestration workers/orchestration`).

## Workflows

All three share one tail: *coding loop → validate → (finish | classify → repair / infra-retry)*. Graphs are in `workflows/graphs.py`, node logic in `workflows/nodes.py`.

```text
new_app : requirements ─[essential question?]→ clarify ─┐
              │ ◄──────────────────────────────────────┘
              ▼
          architecture → decompose → approval ─(revise: feedback)→ requirements
                                        │ approved
                                        ▼
modify  : analyze_project → index_context → modification_plan ─[needs clarification]→ clarify
              → modification_tasks → approval ─(revise)→ modification_plan
                                        │ approved
                                        ▼
        ┌──────────────────────── dispatch_coding → await_coding → apply_coding ─┐ (next task / retry)
        │                                                                          ▼
repair  : analyze_project → classify                                      validate → await_validation → evaluate
              │                                                                          │ pass → finish
              ▼                                                                          │ fail ▼
          infra_retry / repair_plan ───────────────────────────────────────────── classify
```

Deliberate simplifications versus the spec's diagrams:

* *Architecture planning*, *project structure planning* → one LLM call (`ArchitecturePlan` includes `structure`).
* *Screen and feature planning*, *task decomposition* → one LLM call (`TaskGraph`).
* *User request analysis*, *impact assessment* → one LLM call (`ModificationPlan`) followed by deterministic grounding (`ground_plan`).
* *Project upload* is the caller's job; the workflow starts at *project analysis* using `ProjectWorkspace.load_files`.

### State machine (run status)

`running` → `waiting_clarification` | `waiting_approval` | `waiting_coding` | `waiting_validation` → `running` → … → `succeeded` | `failed` | `cancelled`. Terminal states are never overwritten (`RunStore.set_status`).

* Waiting on a human: `OrchestrationService.respond(scope, run_id, reply)`.
  Clarification reply `{"answers": {question: answer}}`; approval reply `{"approved": true}` or `{"approved": false, "feedback": "..."}` (no feedback = reject → `cancelled`).
* Waiting on another service: results are stored in `orch_agent_jobs` first, then the run is woken. The awaiting node reads the stored result, so a result arriving before the run reaches its wait point is not lost.

### Agent roles

There are no free-roaming agents; each role is a bounded function with a typed output:

| Role | Output | Judgment by |
|---|---|---|
| RequirementAnalyzer | `RequirementSpec` | LLM |
| ArchitecturePlanner | `ArchitecturePlan`, `TaskGraph` | LLM + DAG validation + path sanitising |
| ModificationPlanner | `ModificationPlan` | LLM + `ground_plan` (files must exist in the index) |
| `classify_failure` | `FailureClassification` | Rules only (infrastructure checked first) |
| RepairPlanner | `RepairPlan` | LLM, only for non-infrastructure failures |

## Provider abstraction

`providers/`. Configuration is data (`ProvidersConfig`), no vendor is a default.

* **Task-based selection**: `routes[TaskKind] = ordered model keys`.
* **Eligibility is re-checked at call time**: a fallback is used only if the provider is registered, can produce JSON (`supports_json_output`/`supports_json_schema`), and has enough context window. Ineligible fallbacks are never called.
* **Retries**: exponential backoff + jitter for rate limits (honours `retry-after`), timeouts, 5xx. Auth errors skip straight to the next eligible model.
* **Structured output**: output is parsed and validated against the Pydantic model; invalid output gets `schema_repair_attempts` repair rounds, then the next model, then `StructuredOutputError`.
* **Budgets** (`Budget`: tokens, USD, call count) are checked *before* every call using a conservative estimate, and booked after. A cost budget with an **unpriced model fails closed**. Budgets are rebuilt from persisted usage, so they survive restarts.
* **Health**: `LLMRouter.health()`.
* **Prompt hygiene**: every prompt passes through `redact()`; user/project text is wrapped in `<untrusted>` tags and the system prompt tells the model to treat it as data.

Adapters: `AnthropicProvider`, `OpenAICompatibleProvider` (set `base_url` for other OpenAI-compatible vendors/gateways; there is no native Google adapter). Model IDs/prices live in the worker's JSON (`workers/orchestration/providers.example.json`). **Prices are left null because they were not verified; fill them in before using a cost budget.**

## Project intelligence

`intelligence/`. Regex/XML static analysis, no code execution, `defusedxml` for manifests.

Extracts: namespace, applicationId, SDK versions, Gradle plugins/dependencies, manifest (permissions, activities, services, launcher, application class), classes/objects/interfaces/functions, Compose `@Composable`s, Activities/Fragments/ViewModels, Room entities/DAOs, Retrofit endpoints, XML layouts, nav graphs, and tags (auth, payment, network, database, navigation, ui, di).

Known limits: regex parsing, not a real Kotlin/Java parser (nested/generic edge cases, multi-line signatures and Kotlin DSL oddities can be missed); only text under 512 KB is indexed; multi-module Gradle composite logic is not resolved; dependency edges are import-based.

* **Search**: BM25 over path + symbol names (boosted) + content; `retrieve()` returns excerpts within a token budget, plus up to 3 dependencies per hit. Never the whole project.
* **Incremental update**: `ProjectIndex.update(changed, deleted)` skips unchanged hashes and re-analyses only changed files (profile aggregation is recomputed).
* **Isolation**: index is keyed by `ProjectScope(tenant_id, project_id)`; `WorkflowDeps.index_for` asserts the scope. Index text lives in process memory only and is rebuilt from `ProjectWorkspace` after a restart.
* **Never indexed or sent**: unsafe paths (`..`, absolute), build outputs (`build/`, `.gradle/`), `local.properties`, keystores, `.env*`, `google-services.json`, binaries, oversize files. Secret-looking tokens are redacted from any excerpt.

## Persistence (`persistence/store.py`)

Tables (own `OrchBase` metadata; Person 4 should add a migration, see below): `orch_agent_runs` (unique `(tenant_id, agent_task_id)` → idempotent start), `orch_agent_steps`, `orch_agent_artifacts` (versioned plans/decisions/approvals/context refs/validation), `orch_agent_usage`, `orch_agent_jobs` (unique `external_id`, `(run, kind, key)`).
LangGraph checkpoints use LangGraph's own PostgreSQL saver tables.

Stored: metadata, plans, token counts, file *paths* and hashes. **Not stored**: tenant source code, secrets, or anything in a cross-tenant memory. There is no cross-tenant memory yet; when added it must only hold validated, de-identified engineering knowledge.

## Contract with the coding engine (Person 3)

`build_coding_task()` maps the rich task onto the shared `CodingTask`. The contract today has only `instructions` and `context_files`, so the spec's extra fields travel as a JSON envelope in `instructions`:

```json
{"androai_task_envelope": 1, "task_type": "modify", "user_request": "...",
 "implementation_plan": {"task": {...PlannedTask...}, "plan": {...}},
 "context": {"profile": {...}}, "constraints": ["..."], "validation_requirements": ["..."]}
```

`CodingTask.id` is deterministic (`uuid5(run, "coding", task_key#attempt)`), `context_files` = relevant project paths. **Proposed contract change (needs Person 3 + Person 4 approval):** add `task_type`, `user_request`, `implementation_plan`, `context`, `constraints`, `validation_requirements` to `CodingTask`, and `diff_refs`, `review` and `repair_info` to `CodingResult`; then drop the envelope.

Rules orchestration enforces on `CodingResult` before accepting it: paths must be safe and non-sensitive; for `modify`, only files in the approved plan may change (else `out_of_scope_change`); a failed result is retried only if `error.retryable` and under `max_coding_retries`.

## Failure handling and cost controls

| Concern | Control |
|---|---|
| Infinite loops | `max_steps` per run, `max_plan_revisions`, `max_repair_attempts`, `max_infra_retries`, `max_coding_retries`, one clarification round only |
| Infra vs. code failure | Rules classify infrastructure first; infra failures re-run validation (bounded) and end as `infrastructure_failure`, never sent to repair |
| Success | A run succeeds only if the build succeeded and (`require_tests`) the unit test job succeeded with 0 failures |
| Destructive changes | Deleting files, schema/API/config changes → approval is mandatory even when auto-approval is on |
| Invented facts | Plan files must exist in the index; unknown files are dropped and listed in `ungrounded_files`; missing package/namespace aborts rather than guesses |
| Token/cost | Pre-flight + booked usage, per run, persisted |
| Duplicate delivery | `start` idempotent on `AgentTask.id`; results deduped on job id; jobs dispatched at-least-once so **receivers must dedupe on the job id** |
| Crashes | LangGraph checkpoints + `recover()` (stale `running` runs resume from checkpoint; waiting runs with stored-but-unprocessed results are woken) |

## Integration dependencies (open items)

| # | With | Needed | Current stand-in |
|---|---|---|---|
| 1 | Person 4 | `ProjectWorkspace` (`load_files`, `apply_result` → `source_key` snapshot). Orchestration assumes it persists generated files; if Person 3 does that instead, change `apply_coding`. | `_NotConfigured` in `runtime.py` raises on first use. **Workers cannot run end-to-end until this exists.** |
| 2 | Person 4 | Alembic migration for `orch_*` tables (import `androai_orchestration_core.persistence.store.OrchBase` metadata in `db/models.py`) | `RunStore.create_all()` for tests only |
| 3 | Person 4 | `tenant_id` on `AgentTask` (currently passed as a separate task argument) | argument to `start_run` |
| 4 | Person 3 | Celery task name + queue for coding (default `androai_agent.run_coding_task`), idempotent on `CodingTask.id`; result delivered by calling `androai_orchestration.handle_coding_result` | name is a constructor parameter |
| 5 | Person 4 | Build/test task names (defaults `androai_android_build.run_build`, `androai_android_test.run_tests`), results delivered to `handle_build_result` / `handle_test_result`; a `LogReader` for `BuildResult.log_key` (without it the failure log is only `error.message`) | parameters on `CeleryValidationRunner` |
| 5b | Person 4 | Structured error codes in `ErrorInfo.code`: codes starting `infra`, `worker`, `timeout` are treated as infrastructure | rule in `classify_failure` |
| 6 | Person 4 | PostgreSQL + Redis for `make_checkpointer`/`RedisRunLock` | untested |
| 7 | Person 4 | Add `packages/agent-core/orchestration` to `make install-py` and CI (`pip install -e`, `pytest`); I did not touch root Makefile/CI | manual: `pip install -e packages/agent-core/orchestration workers/orchestration` |

## Known limitations

* No HTTP API: the API service should enqueue `start_run`/`respond`/`cancel_run` and read run state; a status/read endpoint is not provided here.
* Coding tasks run sequentially (safe for overlapping files; no parallelism).
* One validation job pair per round (`assembleDebug` + unit tests); lint/instrumented not wired.
* Orchestration does not receive diffs or review results yet (needs the contract change above); it only sees files written.
* `recover()` needs a scheduler (`celery beat`) to run periodically.
* Provider adapters, PostgreSQL saver, Redis lock and Celery dispatch are untested against real services.
* Run-lock TTL (300 s) must exceed the longest single node; LLM timeouts are 120 s × attempts, so long retries inside one node could outlive it.
