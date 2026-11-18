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
