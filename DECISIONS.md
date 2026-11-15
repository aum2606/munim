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

## Phase 1

- **2026-11-16 — Embedding model: `paraphrase-multilingual-MiniLM-L12-v2` via fastembed.** The lightest
  multilingual model fastembed offers (384 dimensions, Apache-2.0, about 220 MB, CPU only, covers Hindi
  and Gujarati). Checked against fastembed's supported list rather than memory. On MunimBench it finds
  97.1% of expected answers and is weak on romanised Hindi (two FAQ questions miss). `EMBEDDING_DIM` is
  fixed at 384 by the column type, so a bigger model needs a migration. Revisit with query rewriting or a
  larger model in Phase 4, using the leaderboard.
- **2026-11-16 — `SEARCH_MAX_DISTANCE=0.65`.** Without a cutoff, vector search always returns its
  nearest neighbours, so a nonsense question retrieved unrelated items and reached the model. Sweeping 0.5
  to 0.8 on the benchmark gave identical results, so 0.65 is simply the middle. The oracle model cannot
  show the false-grounding side of the trade-off: re-tune with a real model in Phase 4.
- **2026-11-16 — Knowledge tools are called by code, not by model tool-calling.** The agent runs
  `lookup_catalog`, `search_knowledge` and `get_business_info` itself and shows the model the results.
  Free-tier models call tools unreliably. The allow-list is still enforced (`ToolBox`) and every call is
  recorded in `agent_runs.tool_calls`.
- **2026-11-16 — Prices are shown to the model but rendered by code.** The model sees formatted catalogue
  prices and may copy them. The price lines customers receive are built by Python from integer paise, and
  the guardrail rejects any amount that is not a catalogue price from that turn.
- **2026-11-16 — NEEDS REVIEW: amounts written in owner policies are allowed.** A delivery threshold such
  as "free above 2000 rupees" lives in an FAQ chunk, which is a tool result, so the price guardrail allows
  it. The catch: a price list uploaded as a PDF would let the bot quote prices from the PDF instead of the
  catalogue. The Knowledge prompt says product prices come only from the catalogue, but no code enforces
  it yet. Decide whether to allow this only for FAQs.
- **2026-11-16 — Known limit: amounts written in words are not detected.** "Two hundred rupees" passes the
  price check. Digits (including Devanagari and Gujarati digits), `k`, lakh and crore are checked.
- **2026-11-16 — Catalogue prices are treated as excluding GST.** Replies say "+ 18% GST", and a blank GST
  cell in an import defaults to 18. Both are assumptions to confirm with real shops. Demo GST rates are
  illustrative.
- **2026-11-16 — `pricing_rules` is deferred to Phase 2.** Nothing reads it until the pricing engine exists.
- **2026-11-16 — The Playground polls instead of streaming.** The dashboard refetches messages every 1.5 s
  while a reply is pending. SSE arrives with the live Inbox in Phase 3, where it is needed.
- **2026-11-16 — Customers are never left in silence.** If every model in the chain fails, the conversation
  is handed to a person with the localized holding message, instead of retrying while the customer waits.
- **2026-11-16 — NEEDS REVIEW: canned replies were written by us.** The Hindi and Gujarati sentences in
  `orchestrator/messages.py` need a native speaker's review. Unknown languages get English.
- **2026-11-16 — Uploads are checked by content and stored under random names.** Type sniffing (PDF
  header, Office zip markers, UTF-8 text), a bounded read for the size limit, parsers capped at 300 PDF
  pages and 5000 spreadsheet rows. Gap: Starlette spools a whole request before our check, so a
  request-size limit at the reverse proxy is still needed (Phase 5).
- **2026-11-16 — The catalogue goes to the LLM only for column mapping,** as headers plus three sample
  rows. It is the owner's own data, but it does reach whichever provider is configured: use a local model
  for a sensitive price list.
- **2026-11-16 — Embedding happens in the worker only.** The API never loads the model, so it starts fast
  and stays small. A new catalogue item or FAQ is searchable once the worker has embedded it.
- **2026-11-16 — Docker volume `app_files` instead of `uploads`.** The name `uploads` collided with a
  volume left by the old project (`munim_uploads`, 46 tenant folders). The old volumes are untouched.
- **2026-11-16 — MunimBench v0.1 phrasings are templated per language.** They are cleaner than real
  messages; v0.2 adds messier ones. The CI run uses an oracle model that answers from gold labels, so it
  checks retrieval, pricing and guardrails around the model, not the model itself.
