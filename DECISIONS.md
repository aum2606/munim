# DECISIONS.md

Assumptions and deviations from `BUILD_PLAN.md`. Newest at the bottom of each phase. Entries marked
`NEEDS REVIEW` touch the data model, money handling, tenancy or agent boundaries and need a human
look before they are relied on.

Format: **date — decision.** Reason.

## Phase 0

- **2026-11-15 — Repo reset and plan v2.** v1 grew past what a small team can finish. Scope was cut
  (one vertical, WhatsApp only, four agents, Postgres-only queue), a free-tier budget was added, and
  MunimBench / adversarial price suite / replay regression were added as the differentiators.
  Old history is kept only in a local backup.
- **2026-11-15 — Added `backend/app/services/`.** `AGENTS.md` says business logic lives in services,
  agents or tools, but the repo map had no services folder. Auth and user management are the first
  services. The map in `AGENTS.md` now lists it.
- **2026-11-15 — No `prompt_versions` table.** The plan listed one, but it would be the only table
  without `tenant_id`, which breaks the tenancy rule. `agent_runs.prompt_version` stores
  `<template>@<sha12>` instead. If replay (Phase 4) needs a registry, add a tenant-scoped table
  then.
- **2026-11-15 — Trimmed columns on `tenants` / `tenant_settings`.** Phase 0 creates only the columns
  something uses today (`tenants`: name, business_type, timezone). GSTIN, state code, address, phone,
  logo and the remaining settings arrive with the onboarding and quote phases, each in its own
  migration.
- **2026-11-15 — Scheduler loop deferred.** The plan lists "worker + scheduler loop" in Phase 0. The
  only scheduled work is follow-ups (Phase 3), so the worker is queue-only now; periodic jobs will
  be added when there is something to schedule.
- **2026-11-15 — `agent_runs.message_id` has no foreign key yet.** `messages` does not exist until
  Phase 1; the FK is added in that migration.
- **2026-11-15 — Real embedder and transcriber are not implemented yet.** Phase 0 delivers the
  interfaces and fakes only. `sentence-transformers` and `faster-whisper` pull in large
  dependencies (torch); they are added in Phase 1 / Phase 3 where they are first used.
- **2026-11-15 — No shadcn/ui in the dashboard.** The plan's stack names it, but its CLI and
  dependencies are not needed for a login screen. Plain Tailwind for now; add shadcn components when
  a screen needs one (Phase 1).
- **2026-11-15 — Typescript pinned to 6.0.x.** `typescript-eslint` does not yet support TypeScript 7.
  Revisit when it does.
- **2026-11-15 — `make` is not installed on the Windows dev machine.** The Makefile targets are plain
  shell one-liners; on Windows run the underlying commands (or install `make` via scoop/choco).

### Security decisions (Phase 0)

- **Refresh token lives in an httpOnly, SameSite=Strict cookie scoped to `/api/v1/auth`;** the access
  token (15 min) is held in browser memory only. Neither is in localStorage, so XSS cannot steal a
  long-lived credential, and SameSite=Strict blocks cross-site use of the cookie. Requires the
  dashboard and API on one origin (Vite proxy in dev, reverse proxy in prod), so no CORS is needed.
- **Refresh tokens rotate and are stored as SHA-256 hashes.** Replaying a rotated-out token revokes
  all of that user's sessions (assumed theft). Deactivating a user also revokes their sessions.
- **User is re-loaded from the DB on every authenticated request.** Role changes and deactivation
  take effect immediately instead of when the access token expires.
- **Login does not reveal whether an email exists** (same response; a dummy hash is verified for
  unknown emails so timing matches). 5 failed attempts lock the account for 15 minutes (persisted in
  Postgres, so it survives restarts and multiple API instances).
- **Registration is open by default** (`ALLOW_REGISTRATION=true`) with no email verification, because
  self-hosters need a first account. Set it to `false` once the owner exists. Add email
  verification / invite-only before any public SaaS use.
- **Validation errors never echo input** (FastAPI's default would return the submitted password).
  Request bodies reject unknown fields. Passwords are capped at 128 chars to bound Argon2 work.
- **`SECRET_KEY` is validated in prod** (>= 32 chars, not a placeholder). API docs are disabled in
  prod. Security headers are set on every response. Compose binds all ports to 127.0.0.1.
- **Logs and `agent_runs.error` / `jobs.last_error` store exception class names only,** never
  messages, because messages can contain customer text. Emails and phone numbers are redacted from
  log fields. `agent_runs.input/output` may contain customer text: it must be deleted with the
  customer in the Phase 5 deletion endpoint.
- **No rate limiting yet on API routes** beyond the login lockout. Per-IP/per-key limits are a Phase 5
  task.
