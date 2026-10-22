# Decisions

## 2026-10-22 ? Phase 0 scope and layout
- Implement only Phase 0; future domain packages are empty Python packages, not placeholder features.
- `.github/` is the CI directory specified in BUILD_PLAN section 13. No additional top-level source directories.
- Use email globally unique for unambiguous email/password login. Login and registration are the only unscoped identity discovery operations; both live in repositories. All authenticated access uses TenantContext.
- NEEDS REVIEW: Add `refresh_sessions`, a tenant-scoped persisted refresh-token session with rotation and revocation, to support secure refresh/logout. Keep `agent_runs.message_id` nullable without a foreign key until messages are introduced in Phase 1.
- Store only redacted agent input/output in traces; redact nested PII and sensitive keys before persistence. Trace failures contain error class names only.
- Use httpx directly inside the LLM provider, following the OpenAI-compatible Chat Completions structured-output format: https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat . No provider SDK elsewhere.
- SQLAlchemy async sessions are request/task scoped: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html . JWT verification fixes HS256 and requires expiry, issuer, subject, tenant and token kind: https://pyjwt.readthedocs.io/en/stable/usage.html .

## 2026-10-22 ? Browser session and scaffolding boundaries
- Tokens stay in memory to avoid persistent browser token storage; a reload requires login. The typed client refreshes access tokens during an active page session and logout revokes its refresh session.
- Phase 0 contains no pricing code, customer messaging, or business agents. Pricing coverage and outbound price guardrails become active with their Phase 1/2 implementations.
- Demo seeds and the full golden eval harness remain in their specified phases; Make targets exist now with honest foundation-only behavior.
- Local Windows tools use workspace-owned caches. Python 3.12 and dependencies are downloaded for verification; generated artifacts stay ignored.

- Development host ports are 57432 (Postgres) and 56379 (Redis) to avoid existing services on 5432 and 55432. Container service ports remain standard; CI exports its service URLs.

- API uses host port 18000 because another project already occupies 8000; no unrelated services are stopped.

- NEEDS REVIEW: Alembic owns its standard unscoped `alembic_version` infrastructure table; it is not application tenant data. All five application tables follow the specified tenancy rule. Migration review added extension installation and enum cleanup on downgrade.

- arq requires at least one function, so Phase 0 registers a diagnostic heartbeat task. No business jobs run before their planned phases.

- A portable GNU Make 4.4.1 was downloaded via winget into the ignored workspace cache (installer hash verified); no global installation or PATH change. Source: https://sourceforge.net/projects/ezwinports/files/ .

- Settings resolve the repository-root `.env` as well as the working-directory `.env`, so all root Make targets share one configuration. Exported variables take precedence; Compose injects its container URLs.

## 2026-10-22 - Validation and delivery
- All Phase 0 implementation and local acceptance checks pass. Hosted GitHub CI cannot be observed without a remote/push; it is recorded as pending rather than claimed green. Phase 1 is not started.
- Docker build contexts exclude local environment files; Compose injects runtime configuration.

## 2026-10-22 - Phase 1 scope and schema
- Phase 0 is pushed to origin/master. All validation steps in https://github.com/aum2606/munim/actions/runs/39802295368 passed; only setup-uv post-job cache saving remains. Treat completed validation checks as the phase gate and continue while infrastructure cleanup finishes; record the final run conclusion when available.
- NEEDS REVIEW: Phase 1 adds `catalog_imports` for persisted preview/mapping/commit and `widget_sessions` for expiring hashed bearer sessions. Add `knowledge_gaps` now because the Phase 1 acceptance criterion requires it. Parent links use composite tenant foreign keys.
- NEEDS REVIEW: Messages gain `processed_at` and `in_reply_to_id` for durable batching, retries and outbound idempotency. Channel external IDs are scoped to the conversation in the web-only phase. Agent-run message links become composite foreign keys when messages exist.
- Embedding storage is VECTOR(1024), matching the default config. Runtime configuration must match the migrated dimension. Changing dimensions requires an explicit migration and re-embedding.
- Retrieval follows pgvector SQLAlchemy cosine/HNSW and Postgres full-text docs: https://github.com/pgvector/pgvector-python and https://www.postgresql.org/docs/16/textsearch-controls.html . Queued tasks follow https://arq-docs.helpmanual.io/ .

- Phase 0 final CI: initial run failed only in setup-uv cache saving after 5 minutes; disabled optional uv cache saving. Corrected run 39803825505 is successful.
- Migration ca741ed81029 reviewed by hand: name the audit unique constraint, install cyclic message/audit foreign keys only after both tables exist, remove them before downgrade. Fresh upgrade/drift check/downgrade/upgrade pass.

- Catalogue XLSX numeric values are read as raw XML text, preventing automatic float conversion of money. openpyxl generates the text-valued template; formulas are rejected. CSV/XLSX imports have bounded upload/expanded sizes and rows.
- The fake LLM accepts an explicit offline demo response factory in addition to hashed scripts. Tests can continue using strict scripts; no fallback calls a real provider. Custom-header mapping uses structured bindings, never edits cell values, and always requires owner commit.
