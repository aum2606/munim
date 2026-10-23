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

- Document uploads persist before queueing; a queue outage leaves a visible pending document with an explicit retry endpoint. The worker writes failure status and a safe reason, and reprocessing replaces chunks atomically.
- Chunk size is 500 whitespace-delimited tokens with 75-token overlap, retaining page and heading metadata. This is a deterministic approximation until a model-specific tokenizer is selected. Each bounded FAQ is one chunk.
- API/worker share an uploads volume. PDF/DOCX/TXT parsing is offline and runs in a thread. Uploaded URLs and OCR remain outside Phase 1. Parser references: https://pypdf.readthedocs.io/en/stable/user/extract-text.html and https://python-docx.readthedocs.io/en/latest/ .

- One full local regression run failed during Postgres testcontainer startup with a Docker 500 before any DB tests ran. Docker health recovered; the unchanged full suite passed on rerun. No tests were skipped.

- Search merges full-text and cosine candidates via reciprocal-rank fusion, requiring cosine distance <= 0.45 for semantic-only candidates. Fake embeddings are a deterministic development aid, not semantic-quality evidence. Catalogue lookup prioritizes SKU and aliases before trigram/hybrid. Currency-bearing chunks are excluded so vector text cannot authorize money.

- NEEDS REVIEW: Router entities use a typed product/quantity/date object instead of arbitrary dict keys, so strict JSON-schema providers can require `additionalProperties=false`. The intended information is unchanged.
- Phase 1 responder output must exactly match a deterministic message assembled from cited tool facts (with a localized prefix). This conservative restriction prevents uncited prose/promises from reaching customers; one retry then handoff handles violations. Knowledge answer_points are trace-only, never evidence. Broader grounded paraphrasing can be evaluated in later phases.
- Agents explicitly gate tool execution; actual Python tool invocations are recorded in agent_runs. The offline demo factory provides deterministic agent responses only when LLM_PROVIDER=fake; golden tests use hash-scripted FakeLLM outputs.

- Knowledge gaps are persisted for unsupported or blocked answers. Guardrail exhaustion/explicit human requests switch the conversation to human mode and stop later AI replies. The full Handoff agent, handoffs table, owner reply actions and notifications remain in Phase 3.
- Each inbound message receives a durable queue job ID; jobs defer by DEBOUNCE_SECONDS, serialize under a tenant/conversation Redis lock, and batch pending messages. Database processed markers and a unique outbound in_reply_to_id protect retries. Busy locks requeue with bounded retries; no model determines dispatch.

- Public widget credential discovery is the second explicit pre-tenant auth exception: resolve a tenant only by its public widget key or an unexpired hashed random bearer token. All subsequent message/stream queries use TenantContext and the bound conversation. Tokens never appear in URLs.
- Only widget paths permit wildcard CORS, with bearer headers and no cookie credentials. Owner routes retain configured origins. Redis atomically rate-limits IP/tenant requests. Streams rotate after a bounded interval so expiry is rechecked; one-shot SSE supports deterministic snapshots/reconnection.

- Catalogue API views add server-formatted display_price strings; dashboard code performs no money arithmetic. The two Pydantic computed_field/property decorators require narrowly scoped mypy prop-decorator ignores (all other strict checks remain enabled). Tests exclude this read-only property when constructing a PUT request.

- Dashboard Playground and the embedded widget share the typed streaming client from widget/src/client.ts; the dashboard Docker build copies that source. All dashboard server state uses TanStack Query. Read-only Inbox deliberately exposes no staff sending/takeover actions before Phase 3.
- Mapping changes must be saved through preview before commit; UI blocks stale or invalid previews. SQLAlchemy runtime engines hide SQL parameter values from exception logs.

- Repeated local Postgres readiness and browser request timeouts occurred when fresh database containers and six browsers ran concurrently. Validation is now sequential with two Playwright workers. Ephemeral test Postgres uses a bounded 512 MB tmpfs data directory to avoid host-filesystem startup variability; it remains real Postgres with unchanged migration, isolation and application assertions.

- Corrected the owner browser test to wait for the Inbox heading before checking read-only controls. Its prior immediate count could inspect the previous Playground DOM during navigation; the no-textbox assertion remains unchanged in meaning and now uses Playwright retrying assertions.

- Boundary review found that Decimal's default precision could round an unusually long fractional amount before the integer-paise check. Parsing now bounds input length and uses enough local precision to reject fractional paise exactly. Whitespace-only FAQs/gap answers are rejected, and make test-be now enforces pricing branch coverage >=100%.

- Demo seeds use fixed tenant/document IDs and catalogue upserts, preserve existing owner passwords, and require DEMO_SEED_PASSWORD from env for new owners. All demo names, emails, catalogue amounts and policies are synthetic; no real customer data or credentials are embedded.
- Demo FAQ chunks are inserted ready by the seeder through repositories, using the configured Embedder; production uploads continue through the worker pipeline. Golden widget tests use scripted FakeLLM responses keyed by actual agent/input hashes, FakeEmbedder, and real Postgres/Redis.

- Provider HTTP failures and malformed document package/XML errors now become visible failed ingestion states, allowing the existing explicit retry flow instead of leaving a document processing indefinitely. A fake timeout test proves failure details are redacted and retry succeeds.

## 2026-10-23 - Phase 2 requirements and quotations

- NEEDS REVIEW: Introduce the minimal leads aggregate in Phase 2 because requirements must persist on a lead and quotes reference it. Phase 3 retains lead scoring/events/follow-ups.
- Requirement JSON Schema supports bounded string/integer/boolean slots with enum and bounds. Defaults are applied only when the customer explicitly does not know an answer. Python chooses the next two missing questions; the LLM only extracts slot updates.

- NEEDS REVIEW: Pricing rules have typed params: quantity tiers set unit paise; add-ons charge fixed/per-unit paise for an option value; min-order sets quantity; seasonal uses integer basis points. Active rules apply in priority order (higher priority last); largest eligible tier wins within a rule. Seasonal adjustment follows tiers, before add-ons; line discount then quote discount precede tax. Quote discounts allocate proportionally by GST group, flooring paise and assigning the remainder to the final group.
- Tax components are rounded half-up to paise per rate group, then the grand total rounds half-up to the nearest rupee. Unknown customer state follows the spec intra-state fallback; owner can explicitly set place of supply. Rates come only from owner catalogue, not tax inference. CBIC distinction verified: https://cbic-gst.gov.in/hindi/faq.html and https://cbic-gst.gov.in/about-gst.html .
