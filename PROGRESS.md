# PROGRESS.md

Source of truth for where we are. Tasks come from `BUILD_PLAN.md` section 15. Tick a task only when
its tests pass; add a one-line note of what was built. Deviations go in `DECISIONS.md`.

**Current phase: 0 (Foundations) is complete. Next: Phase 1, first task (models + extensions).**

## Phase 0 — Foundations

- [x] Repo scaffold, `uv` project, `.gitignore`, `.gitattributes`, `.env.example`
- [x] Docker Compose (postgres+pgvector, api, worker, dashboard), Makefile, GitHub Actions CI
- [x] Config via pydantic-settings (prod rejects weak `SECRET_KEY`), structured JSON logging with
      email/phone redaction, central domain-error mapping, `/health` and `/ready`
- [x] Models + migration `0001`: `tenants`, `tenant_settings`, `users`, `refresh_tokens`,
      `agent_runs`, `jobs`; a test fails if models and migrations drift apart
- [x] Auth: register / login / refresh (rotating) / logout / `/me`, Argon2, JWT, lockout,
      owner-only `/users` CRUD, `TenantContext`, tenant-scoped repositories
- [x] `LLMClient` + provider fallback chain over OpenAI-compatible endpoints + `FakeLLM`,
      structured output with one validated retry
- [x] `Embedder` + `FakeEmbedder`, `Transcriber` + `FakeTranscriber` (real models arrive with the
      features that use them)
- [x] `agent_runs` recording context manager (`llm/recording.py`), success and failure both logged
- [x] Postgres job queue (`FOR UPDATE SKIP LOCKED`, leases, backoff, dead letters) + worker
- [x] Dashboard: login, register, protected routes, layout shell (React + Vite + TS + Tailwind +
      TanStack Query, English string catalogue)

### Phase 0 acceptance (BUILD_PLAN.md section 15)

| Criterion | Result |
|---|---|
| `make dev` brings everything up with no paid keys | `docker compose up -d --build` (the command `make dev` runs): postgres, api, worker, dashboard all up, api healthy, no API keys set |
| register/login works from the dashboard | Registered via the dashboard's proxy, then signed in through the UI in a browser at 375px: "Welcome, Smoke" |
| CI green | workflow committed; the first run happens on push |
| user tenant-isolation test passes | `tests/integration/test_users.py::test_tenant_isolation_for_users` passes |
| a job is run exactly once by two competing workers | `tests/integration/test_jobs.py::test_two_competing_workers_run_each_job_exactly_once` passes |

Commands run: `cd backend && uv run pytest` (57 passed, 94% line+branch coverage),
`uv run ruff check . && uv run ruff format --check . && uv run mypy` (clean, `mypy --strict`),
`cd dashboard && pnpm lint && pnpm typecheck && pnpm test && pnpm build` (8 tests passed).

## Phase 1 — Knowledge + Playground

- [ ] Models: documents, chunks, catalog_items, pricing_rules, customers, conversations, messages, knowledge_gaps (+ `pgvector` / `pg_trgm` extensions)
- [ ] `parse_inr` price parser
- [ ] Catalogue XLSX template, import with LLM column mapping, preview, commit
- [ ] Document / FAQ ingestion job (parse, chunk, embed); real local `Embedder`
- [ ] Hybrid search tool + catalogue lookup tool
- [ ] Router, Knowledge, Responder agents; guardrails (price check first)
- [ ] Orchestrator v1: advisory lock, debounce, dispatch, deterministic handoff, knowledge gaps
- [ ] Playground adapter + SSE; Playground page with trace panel; Knowledge pages; read-only Inbox
- [ ] Seeds: printing press + photographer
- [ ] First 100 MunimBench items; `make eval` (FakeLLM) in CI
- [ ] Acceptance: >= 20 scripted questions (English + Hinglish + Gujlish) with zero hallucinated prices; unanswerable questions create knowledge gaps; injected wrong price is blocked

## Phase 2 — Quotes

- [ ] `requirement_schemas` (printing + photography), `leads`, `lead_events`, `quotes`, `quote_items`
- [ ] Pricing engine: 100% branch coverage + Hypothesis property tests
- [ ] Quote agent (slot filling + mapping), FY quote numbering, PDF
- [ ] Approval queue; approve sends to customer; rule-based lead scoring + stages
- [ ] Acceptance: printing and photography conversations end in a PDF with hand-calculated totals

## Phase 3 — WhatsApp + voice + handoff

- [ ] `channel_accounts` (encrypted credentials), WhatsApp adapter, idempotency, retries, dead letters
- [ ] 24h window logic; templates off by default
- [ ] `faster-whisper` Transcriber; voice notes through the pipeline; low-confidence confirmation
- [ ] Live inbox with take-over; follow-up drafts; owner WhatsApp notifications
- [ ] Acceptance: Hinglish voice note to approved PDF on a WhatsApp test number; duplicate webhooks ignored

## Phase 4 — Benchmark, red team, replay

- [ ] MunimBench to 300–500 items + ~50 audio clips, datasheet, CC BY 4.0
- [ ] Eval runner + multi-model leaderboard
- [ ] Adversarial price suite (500+ attacks), regression cases saved
- [ ] Prompt versioning + `make replay` + CI gate on price accuracy
- [ ] Cost / latency report from `agent_runs`

## Phase 5 — Pilot + release

- [ ] Metrics page; rate limits; upload size/type validation
- [ ] Self-host guide (Compose + Cloudflare Tunnel), nightly `pg_dump`
- [ ] Privacy notice + customer data deletion endpoint (cascades `agent_runs`)
- [ ] Pilot with 2–3 real businesses; owner guide
- [ ] README with architecture diagram, demo, leaderboard and reliability numbers

## Log

- 2026-11-15 — Phase 0 implemented. See acceptance table above.
