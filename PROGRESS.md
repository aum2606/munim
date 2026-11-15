# PROGRESS.md

Source of truth for where we are. Tasks come from `BUILD_PLAN.md` section 15. Tick a task only when
its tests pass; add a one-line note of what was built. Deviations go in `DECISIONS.md`.

**Current phase: 1 (Knowledge + Playground) is built. Next: Phase 2 (Quotes), first task: the `requirement_schemas`, `leads` and `quotes` models.**

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

- [x] Models + migration `0002`: documents, chunks, catalog_items, customers, conversations, messages, knowledge_gaps, import_jobs, plus the `vector` and `pg_trgm` extensions and HNSW / GIN indexes. `pricing_rules` moved to Phase 2 (DECISIONS).
- [x] `parse_inr` and `format_inr` (`pricing/inr.py` at 100% branch coverage)
- [x] Catalogue import: XLSX template, name-based column mapping, LLM mapping fallback (checked against the real headers), preview with row errors, commit by SKU
- [x] Document and FAQ ingestion: content sniffing, size limits, PDF/DOCX/TXT parsing, chunking, embedding in the worker; real local embedder (fastembed, 384-dim multilingual)
- [x] Hybrid search (vector + full-text, merged with RRF) and catalogue lookup (SKU, alias, trigram, hybrid) with a relevance cutoff
- [x] Router, Knowledge and Responder agents; guardrails (price, leak, length); prompts in `agents/prompts/*.jinja` with versioned hashes
- [x] Orchestrator v1: advisory lock, debounce, deterministic dispatch, handoff (also when no model is available), knowledge gaps
- [x] API: catalogue and import, documents, FAQs, knowledge gaps, playground, conversations, agent runs
- [x] Dashboard: Knowledge (catalogue and import wizard, documents, FAQs, gaps), Playground with trace panel, read-only Inbox
- [x] Seeds: printing press (15 items, 10 FAQs) and wedding photographer (10 items, 8 FAQs); `make seed`
- [x] MunimBench v0.1: 100 items, datasheet, runner and an oracle model for CI; `make eval`
- [ ] Not built yet: editing one catalogue item in the dashboard (the API supports it), SSE streaming (the Playground polls instead, see DECISIONS)

### Phase 1 acceptance (BUILD_PLAN.md section 15)

| Criterion | Result |
|---|---|
| At least 20 scripted questions (English, Hinglish, Gujlish) with zero hallucinated prices | MunimBench runs 100 items in all five languages through the full pipeline: **0 hallucinated amounts and price accuracy 100%**, with real multilingual embeddings in Docker and with fake embeddings in CI. The model is a scripted stand-in, so this proves retrieval, price rendering and guardrails. **It does not prove real-model quality, which has not been run (no model keys).** |
| Unanswerable questions create knowledge gaps | `test_unanswerable_question_logs_a_gap_and_says_it_will_check`: repeats are counted, and answering a gap creates an FAQ |
| An injected wrong price is blocked | `test_a_wrong_price_is_blocked_and_regenerated` (one regeneration) and `test_a_price_that_stays_wrong_is_never_sent_and_a_human_takes_over`; guardrail unit tests cover Devanagari and Gujarati digits, `k` and lakh shorthand, and sub-paisa amounts |
| `make eval` (fake model) runs in CI | `tests/integration/test_benchmark.py` runs the harness inside `pytest`, which CI runs |

Real-embedding retrieval on the benchmark (`benchmark/reports/oracle-local.md`): 97.1% of items find
their expected catalogue item or FAQ. Two romanised-Hindi FAQ questions miss ("kitne baje tak khule
rehte ho", "aapki dukaan kahan hai"). Cutoffs from 0.5 to 0.8 behave identically, so the limit is the
embedding model, not the cutoff.

Commands run: `cd backend && uv run pytest`, `uv run ruff check . ../benchmark`,
`uv run ruff format --check . ../benchmark`, `uv run mypy` (strict, clean); `cd dashboard && pnpm lint &&
pnpm typecheck && pnpm test && pnpm build`; `docker compose up -d --build`, `python -m seeds.load` and
`python -m benchmark.run --embedder local` inside the worker; a browser run at 375px (login, catalogue,
one Playground turn through the worker).

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
