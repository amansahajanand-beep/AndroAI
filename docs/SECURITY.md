# Security

## Current baseline

- No real credentials in the repo. `.env` is git-ignored; `.env.example` has placeholders only.
- API refuses to start if required config is missing; `JWT_SECRET` must be ≥32 chars and not a placeholder in `production`.
- CORS limited to `APP_URL`.
- Errors never leak stack traces (`internal_error` envelope).
- Contracts reject unknown fields.

## Must be decided before Phase 1 handles real users/builds

- **Auth**: JWT issuance/refresh, password hashing, rate limiting (none implemented).
- **Build sandboxing**: generated code is untrusted. Build/test workers must run unprivileged, with resource limits and restricted egress, in isolated images; never inside the API container.
- **Secrets**: LLM keys and storage credentials via a secrets manager in deployed environments, not `.env`.
- **Tenant isolation**: per-project storage prefixes and authorization checks on every `project_id`.
- **Dependencies**: enable Dependabot / vulnerability scanning in CI.

Report vulnerabilities privately to the repository owners.

## AI orchestration (Person 2)

- **Untrusted input.** User requests and uploaded project content are wrapped in `<untrusted>` tags and the model is instructed to treat them as data; instructions found in a project are never executed. This reduces, but does not eliminate, prompt-injection risk, so model output is never trusted structurally: it is schema-validated, paths are normalised, plan files are checked against the index, and the coding engine's output is path-checked (and, for modifications, scope-checked) before it touches the project.
- **Secrets never reach models.** `local.properties`, keystores, `.env*`, `google-services.json` and similar files are not indexed; every prompt and excerpt is passed through `redact()` (key/token patterns and `secret = value` assignments). Redaction is pattern-based and can miss novel secret formats.
- **No secrets in config.** The provider config names env vars (`api_key_env`); keys are read from the environment/secrets store. Adapters never log keys or prompts.
- **Tenant isolation.** Indexes are keyed by `(tenant_id, project_id)`; run reads/writes through `RunStore` are scoped and return "not found" across tenants; `index_for` asserts the scope. Service-to-service result tasks identify runs by unguessable job ids and must only be reachable by trusted workers (queue ACLs are Person 4's).
- **Stored data.** Runs/plans/usage are metadata; no tenant source or secrets are stored, and there is no cross-tenant memory.
- **Destructive changes** (file deletion, DB/API/config changes) always require explicit human approval.
- **Resource abuse.** Hard token/cost/call budgets, step and retry limits, bounded repair loops, input file size limits.
- **Not covered:** authentication/authorisation of who may call `start_run`/`respond` (API layer), sandboxing of build/test (Person 4), Redis/DB transport security.
