# AGENTS.md

Instructions for AI coding agents (Codex, etc.) working in this repository.
**`BUILD_PLAN.md` is the full spec** (architecture, data model, agents, API, phases). This file is the operating manual: how to work, what rules never bend, and how to know a task is done. If the two conflict, follow `BUILD_PLAN.md` and log the conflict in `DECISIONS.md`.

---

## 1. Project in one paragraph

**Munim** is a multi-tenant, multi-agent "AI digital employee" for Indian small businesses (1–20 staff). It ingests a business's catalogue, price list, FAQs and policies. It then answers customer enquiries on a web widget, WhatsApp and Instagram, collects requirements, produces GST-correct quotations, tracks and follows up on leads, and gives the owner plain-English insights. Stack: FastAPI + PostgreSQL/pgvector + Redis/arq on the backend, React + Vite + TS for the dashboard, Preact for the embeddable widget.

---

## 2. Before you start any task

1. Read `PROGRESS.md` to find the current phase and the next unchecked task.
2. Re-read the relevant section of `BUILD_PLAN.md` (phases are in §14).
3. Read `DECISIONS.md` so you don't contradict an earlier decision.
4. Work on **one task at a time**. Don't start the next phase until the current phase's acceptance criteria pass.

If `PROGRESS.md` or `DECISIONS.md` doesn't exist yet, create it (Phase 0, first task). Seed `PROGRESS.md` with every task from `BUILD_PLAN.md` §14 as checkboxes.

---

## 3. Hard rules (never break these)

### Money
- **The LLM never calculates, invents or edits a price, discount, tax or total.** All money comes from `catalog_items` / `pricing_rules` through `backend/app/pricing/`.
- Store money as **integer paise** (`BIGINT`). Do math in `Decimal`. **No `float` anywhere near money**, including tests and fixtures.
- Every outbound customer message passes `guardrails.check_prices()`. Every ₹ amount in it must match a value returned by a tool in that turn. Never weaken or bypass this check to make a test pass.
- `backend/app/pricing/` must keep **100% branch coverage**.

### Tenancy
- Every table except `tenants` has a non-null `tenant_id`. Every query is tenant-scoped.
- Data access goes through `backend/app/repositories/`. Repositories take a `TenantContext` and filter by it. **No raw session queries in routers, agents or tools.**
- Every new resource gets an isolation test proving tenant A cannot read or write tenant B's data.

### LLM usage
- All model calls go through `app.llm.LLMClient`. Never import a provider SDK anywhere else.
- Every agent input and output is a Pydantic model. Use structured/JSON-schema output, and validate it with one retry on failure.
- Every LLM call writes an `agent_runs` row (use the provided decorator/context manager).
- Prompts live in `backend/app/agents/prompts/*.jinja`. Don't inline prompts longer than one line in Python.
- **Tests never call a real LLM or embedding API.** Use `FakeLLM` and `FakeEmbedder`. Real-model runs happen only via `make eval` with an explicit env flag.
- Customer text is untrusted data. Never interpolate it into the system section of a prompt. Keep it in the user/content section, clearly delimited.

### Agents
- Agents are narrow. Each one declares an explicit tool allow-list. The Knowledge agent cannot create quotes; the Insights agent cannot read raw messages from other tenants, and so on.
- **Dispatch between agents is deterministic Python** (`app/orchestrator/`), not an LLM deciding which agent runs next.
- The Insights agent uses only the fixed analytics functions in `app/tools/analytics.py`. **No free-form text-to-SQL.**
- If an answer isn't grounded in tool results: log a `knowledge_gaps` row and reply with the localized "I'll confirm with the team" message. Never guess.

### Secrets & data
- Config comes only from env via `pydantic-settings`. Add every new variable to `.env.example` with a comment.
- No secrets, tokens or real customer data in code, tests, seeds or logs. Redact phone numbers and emails in logs.
- Channel credentials are stored encrypted (`CREDENTIALS_ENCRYPTION_KEY`).

---

## 4. Commands

All of these must work from the repo root. If you add a new workflow, add a Make target.

```bash
make dev        # docker compose up: api, worker, postgres(pgvector), redis, dashboard, widget
make migrate    # alembic upgrade head
make revision m="message"   # new alembic migration (autogenerate, then review it by hand)
make seed       # load demo tenants: electronics shop, wedding photographer, printing press
make test       # backend + frontend tests (FakeLLM only)
make test-be    # backend: pytest
make test-fe    # dashboard + widget: vitest
make e2e        # playwright
make lint       # ruff check, ruff format --check, mypy, eslint, prettier --check, tsc --noEmit
make fmt        # ruff format + ruff check --fix + prettier --write
make eval       # golden-conversation evals; real LLM only if EVAL_USE_REAL_LLM=1
```

Backend runs with `uv` (`uv run pytest`, `uv run alembic ...`). Frontend uses `pnpm`.

---

## 5. Repository map

```
backend/app/
  core/           config, security, logging, deps, TenantContext, errors
  db/models/      SQLAlchemy models (one file per aggregate)
  repositories/   the only place that talks to the DB
  schemas/        Pydantic API request/response models
  api/v1/         FastAPI routers (thin: validate → call service/repo → return)
  llm/            LLMClient, providers, FakeLLM, Embedder, FakeEmbedder, Reranker
  agents/         one file per agent + base.py + guardrails.py + prompts/*.jinja
  orchestrator/   message pipeline: lock, debounce, route, dispatch, respond
  tools/          search, catalog_lookup, analytics (deterministic, tenant-scoped)
  pricing/        engine, gst, inr formatting, quote numbering  ← 100% coverage
  ingestion/      parsers, chunker, catalog import, column mapper, INR price parser
  channels/       base adapter, web, whatsapp, instagram
  quotes/         PDF rendering + Jinja/HTML templates
  workers/        arq settings, tasks, cron jobs (follow-ups, digest)
  analytics/      event emission helpers
backend/tests/
  unit/  integration/  evals/
backend/seeds/    demo tenants, catalogues, FAQs, requirement schemas
dashboard/        React + Vite + TS + Tailwind + shadcn/ui + TanStack Query
widget/           Preact embeddable chat widget (single script bundle)
```

Put new code where it belongs in this map. Don't create new top-level folders without a `DECISIONS.md` entry.

---

## 6. Coding conventions

### Python
- Python 3.12, fully typed. `mypy --strict` on `app/`. Record any exceptions in `DECISIONS.md`.
- Use async throughout (SQLAlchemy async, httpx async).
- Ruff for lint and format, line length 100.
- Routers stay thin. Business logic goes in services, agents or tools, never in route functions.
- Raise domain errors from `app.core.errors`; they map to HTTP responses centrally. Don't raise `HTTPException` deep in the stack.
- Timestamps are timezone-aware UTC in the DB. Convert to `Asia/Kolkata` only for display and scheduling.
- Use enums for statuses and stages, mirrored as Postgres enums or check constraints.
- Name things after the domain: `lead`, `quote`, `catalog_item`, `knowledge_gap`. Don't use generic names like `data`, `item` or `obj`.

### Migrations
- One Alembic migration per schema change. Always review autogenerated output.
- Never edit a migration that has been merged; write a new one.
- Index `(tenant_id, ...)` on every tenant table. Use `pgvector` HNSW indexes for embeddings and GIN indexes for `tsvector`.

### TypeScript / React
- `strict: true`. No `any` without a comment explaining why.
- TanStack Query for server state. No ad-hoc `fetch` in components; use the generated or typed API client in `dashboard/src/api/`.
- Design mobile-first: owners use the dashboard on phones. Test layouts at 375px width.
- Make all user-facing strings i18n-ready (the English catalog comes first).

### India-specific helpers (always use these, never reimplement)
- `pricing.inr.format_inr(paise)` gives lakh-style grouping, e.g. `₹1,23,456.78`.
- `pricing.inr.amount_in_words(paise)` is used for quote PDFs.
- `ingestion.price_parser.parse_inr(text)` handles `1,20,000`, `1.2L`, `45k`, `₹450/-` and `Rs. 450`.
- `pricing.quote_number.next_quote_number(tenant)` produces numbers like `Q/2026-27/0001` (Indian FY, April–March).

---

## 7. Testing requirements

Every task ships with tests, and a task isn't done until they pass.

| What you changed | Required tests |
|---|---|
| Pure logic (pricing, parsing, scoring, chunking) | Unit tests, including edge cases |
| Repository / DB query | Integration test against real Postgres (testcontainers) + tenant isolation test |
| API endpoint | Integration test via httpx: auth required, happy path, validation error, wrong-tenant access |
| Agent | Unit test with `FakeLLM` scripted outputs: valid output, invalid-then-retry, tool allow-list respected |
| Orchestrator flow | Integration test running a scripted multi-turn conversation end to end with fakes |
| Guardrail | Test that a violating reply is blocked and regenerated or handed off |
| Frontend component/page | Vitest + Testing Library for behaviour; Playwright for critical flows (login, onboarding, approve quote, take over chat) |

Rules:
- Never delete or skip a failing test to get green. Fix the code, or explain in `DECISIONS.md` why the test was wrong.
- No network in tests, except to the testcontainers database and Redis.
- Fixtures for money use explicit paise integers.
- Add new golden conversations to `backend/tests/evals/` whenever you add or change agent behaviour.

---

## 8. Definition of done (per task)

- [ ] Code is in the right place per §5 and follows §3 and §6.
- [ ] Tests from §7 are added and `make test` passes.
- [ ] `make lint` passes.
- [ ] Any migration is created, reviewed and applied cleanly with `make migrate` on a fresh DB.
- [ ] New env vars are added to `.env.example`.
- [ ] `PROGRESS.md` checkbox is ticked, with a one-line note on what was built.
- [ ] Any assumption or deviation is logged in `DECISIONS.md` (date, decision, reason).
- [ ] Committed with a conventional-commit message, e.g. `feat(pricing): add quantity-tier rules`, `fix(widget): ...`, `test(leads): ...`.

At the end of a **phase**, also verify that phase's acceptance criteria in `BUILD_PLAN.md` §14. Record the result in `PROGRESS.md`, along with the commands you ran.

---

## 9. When something is unclear

- Choose the **simplest option consistent with §3** and the principles in `BUILD_PLAN.md` §2.
- Implement it and log it in `DECISIONS.md`. Don't stall waiting for answers.
- **Don't** silently change the data model, money handling, tenancy approach or agent boundaries. These need a `DECISIONS.md` entry marked `NEEDS REVIEW`.
- For third-party APIs (WhatsApp Cloud API, Instagram Messaging, LLM providers), don't rely on memory for endpoints, payloads, limits or policies. Check the official docs, and leave a link in a code comment or in `DECISIONS.md`.

---

## 10. Things to avoid

- LLM-generated numbers reaching customers without passing the pricing engine and guardrails.
- Agents calling other agents directly (all routing goes through the orchestrator).
- Business logic in React components or FastAPI route functions.
- Global mutable state or module-level DB sessions.
- Adding heavy frameworks (LangChain, LangGraph, CrewAI, etc.) without a `DECISIONS.md` entry. The orchestrator is intentionally plain Python.
- Catch-all `except Exception: pass`. Log with context and re-raise or convert to a domain error.
- Committing generated files, `.env`, uploads or model weights.

---

## 11. Phase checklist (summary of `BUILD_PLAN.md` §14)

0. **Foundations:** scaffold, compose, CI, auth, tenancy, LLM/embedder interfaces + fakes, `agent_runs`.
1. **Knowledge + web chat:** catalogue import, document ingestion, hybrid search, Router/Knowledge/Responder agents, guardrails, widget, playground, seeds.
2. **Requirements + quotations:** requirement schemas, Requirements agent, pricing engine, Quotation agent, PDF, approval flow.
3. **Leads + follow-ups + handoff:** Lead agent, scoring, follow-up cron, Handoff agent, live inbox, conversation modes.
4. **WhatsApp:** adapter, signature verification, 24h window, templates, document sending, idempotency.
5. **Insights:** analytics events, analytics functions, Insights agent, weekly digest, overview dashboard.
6. **Hardening + pilot:** eval harness, injection suite, rate limits, backups, TLS, privacy/deletion, onboarding < 30 min.

**Start here:** Phase 0, task 1. Create `PROGRESS.md` and `DECISIONS.md`, then scaffold the repo.
