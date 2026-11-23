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

## Backend platform (Person 4)

Implemented and tested:

- **Passwords**: argon2id; >= 10 chars; login does equal work for unknown emails and returns one generic error; failed logins are audited.
- **Sessions**: short-lived JWT (HS256, `iss`/`typ`/`exp` required, `alg=none` rejected) bound to a DB session row; opaque 384-bit refresh tokens stored as SHA-256, single-use with rotation. Presenting an already-rotated token revokes the whole family (theft detection). Logout, password change/reset, deactivation revoke access tokens immediately.
- **Email verification / reset tokens**: single-use, hashed at rest, expiring (24 h / 30 min); reset never reveals whether an account exists; reset revokes all sessions.
- **Rate limiting**: per IP on auth routes, plus per-account on login (5/min) and forgot-password (3/min). Redis-backed; falls back to per-process counters if Redis is down. `X-Forwarded-For` is trusted only if `TRUST_PROXY_HEADERS=true` (set it only behind our own Nginx).
- **Authorisation**: permission per route (`require_permission`); admin routes need role permissions. Projects are only loaded through `get_owned_project` (tenant filter); cross-tenant ids are `404`. Tests exercise every project/artifact route as a second tenant.
- **Object storage**: private bucket; keys always `tenants/<tenant>/...`, built only through `androai_storage.keys`; every read re-checks the key's tenant prefix (`InvalidKey` -> 403 + security log). Downloads use 5-minute signed URLs (HMAC bound to artifact id + expiry; S3 backends redirect to a presigned URL). Artifact responses are `attachment` + `nosniff`.
- **Upload validation** (ZIP): never extracted to the host filesystem (streamed into object storage). Rejects `..`, absolute paths, drive letters, backslashes, NUL/control chars, symlinks and special files, encrypted entries, duplicate / case-colliding paths, file-vs-directory conflicts. Zip-bomb limits are enforced on actually decompressed bytes (headers can lie): entries <= 20,000, file <= 50 MB, total <= 1 GB, compression ratio <= 100:1, depth <= 40. Upload size cap enforced by Nginx (`client_max_body_size`), by the `Content-Length` check, and again while spooling. Any rejection discards partial output. File modes are dropped (no executable bits).
- **APK uploads**: structure validated, stored, never unpacked or executed on the control plane.
- **Secrets**: `secrets_vault.py` (Fernet, key rotation list) for secrets stored in the DB; `mask_secret` for logs/responses; audit `detail` strips keys named password/token/secret. In production the app refuses to start without `SECRETS_ENCRYPTION_KEY`, S3 storage and a non-placeholder JWT secret.
- **Audit log**: register, login (success/failure), refresh reuse, password events, uploads, project create/delete, artifact URL issue/delete, admin changes.

Known gaps (not done yet): no build sandbox (no build worker exists yet), no CSRF concern today (bearer tokens, no cookies), no MFA, no per-IP limits outside auth routes, no dependency scanning in CI, JWT secret rotation is manual (invalidates sessions), logs are not yet structured/shipped, no malware scanning of uploaded content, blob garbage collection is not implemented.

### Build scheduling and workers (Person 4)

Implemented: pull-model workers authenticated by per-worker tokens (stored hashed, shown once, rotatable); a worker can only read, log to, upload for and complete the one job it currently holds; workers receive **no database or object-storage credentials** (source, artifacts and logs flow through the API); Gradle task names are validated (no `--init-script` style option injection); per-user concurrent/pending job limits and a global queue cap (backpressure); bounded log size; time-limited leases, timeouts, bounded retries; release builds are unsigned and no signing material exists in the platform yet; unavailable runtimes are recorded as `not_run`, a test run with failures or zero executed tests cannot be marked passed.

**Not implemented yet - read before running real builds:** the build *worker process and its sandbox* (non-root, CPU/RAM/disk/process limits, no Docker socket, egress filtering of RFC1918/metadata/internal services, disposable workspace) do not exist; `workers/android-build` is still the skeleton. Until they do, nothing may execute uploaded Gradle code. The scheduler only decides *who may run what*; it does not make execution safe.

## AI orchestration (Person 2)

- **Untrusted input.** User requests and uploaded project content are wrapped in `<untrusted>` tags and the model is instructed to treat them as data; instructions found in a project are never executed. This reduces, but does not eliminate, prompt-injection risk, so model output is never trusted structurally: it is schema-validated, paths are normalised, plan files are checked against the index, and the coding engine's output is path-checked (and, for modifications, scope-checked) before it touches the project.
- **Secrets never reach models.** `local.properties`, keystores, `.env*`, `google-services.json` and similar files are not indexed; every prompt and excerpt is passed through `redact()` (key/token patterns and `secret = value` assignments). Redaction is pattern-based and can miss novel secret formats.
- **No secrets in config.** The provider config names env vars (`api_key_env`); keys are read from the environment/secrets store. Adapters never log keys or prompts.
- **Tenant isolation.** Indexes are keyed by `(tenant_id, project_id)`; run reads/writes through `RunStore` are scoped and return "not found" across tenants; `index_for` asserts the scope. Service-to-service result tasks identify runs by unguessable job ids and must only be reachable by trusted workers (queue ACLs are Person 4's).
- **Stored data.** Runs/plans/usage are metadata; no tenant source or secrets are stored, and there is no cross-tenant memory.
- **Destructive changes** (file deletion, DB/API/config changes) always require explicit human approval.
- **Resource abuse.** Hard token/cost/call budgets, step and retry limits, bounded repair loops, input file size limits.
- **Not covered:** authentication/authorisation of who may call `start_run`/`respond` (API layer), sandboxing of build/test (Person 4), Redis/DB transport security.
