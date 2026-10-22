# Decisions

## 2026-10-22 ? Phase 0 scope and layout
- Implement only Phase 0; future domain packages are empty Python packages, not placeholder features.
- `.github/` is the CI directory specified in BUILD_PLAN ?13. No additional top-level source directories.
- Use email globally unique for unambiguous email/password login. Login and registration are the only unscoped identity discovery operations; both live in repositories. All authenticated access uses TenantContext.
- NEEDS REVIEW: Add `refresh_sessions`, a tenant-scoped persisted refresh-token family with rotation and revocation, to support secure refresh/logout. Keep `agent_runs.message_id` nullable without a foreign key until messages are introduced in Phase 1.
- Store only redacted agent input/output in traces; redact nested PII and sensitive keys before persistence. Trace failures contain error class names only.
- Use httpx directly inside the LLM provider, following the OpenAI-compatible Chat Completions structured-output format: https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat . No provider SDK elsewhere.
- SQLAlchemy async sessions are request/task scoped: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html . JWT verification fixes HS256 and requires expiry, issuer, subject, tenant and token kind: https://pyjwt.readthedocs.io/en/stable/usage.html .

## 2026-10-22 ? Browser session and scaffolding boundaries
- Tokens stay in memory to avoid persistent browser token storage; a reload requires login. The typed client refreshes access tokens during an active page session and logout revokes its refresh session.
- Phase 0 contains no pricing code, customer messaging, or business agents. Pricing coverage and outbound price guardrails become active with their Phase 1/2 implementations.
- Demo seeds and the full golden eval harness remain in their specified phases; Make targets exist now with honest foundation-only behavior.
- Local Windows tools use workspace-owned caches. Python 3.12 and dependencies are downloaded for verification; generated artifacts stay ignored.

- Development host ports are 57432 (Postgres) and 56379 (Redis) to avoid an existing native Postgres on 5432. Container service ports remain standard; CI exports its service URLs.

- API uses host port 18000 because another project already occupies 8000; no unrelated services are stopped.

- NEEDS REVIEW: Alembic owns its standard unscoped `alembic_version` infrastructure table; it is not application tenant data. All five application tables follow the specified tenancy rule. Migration review added extension installation and enum cleanup on downgrade.
