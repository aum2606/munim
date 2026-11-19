# PROGRESS.md

Source of truth for where we are. Tasks come from `BUILD_PLAN.md` section 15. Tick a task only when
its tests pass; add a one-line note of what was built. Deviations go in `DECISIONS.md`.

**Current phase: 3 (WhatsApp + voice + handoff) is built and tested against a fake Meta and a fake speech model. Not yet run against a real Meta test number or real audio, and the Phase 2 real-model check of the quote flow is still pending (needs a provider key). Phase 4 has started: the adversarial price suite is done; replay, benchmark growth and the cost report are next.**

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

- [x] Models + migration `0003`: `requirement_schemas`, `pricing_rules`, `leads`, `lead_events`, `quotes`, `quote_items`, `quote_sequences`; business profile on `tenants` (GSTIN, state, address, phone) and quote terms on settings
- [x] Pricing engine (`app/pricing/`): quantity tiers, add-ons, minimum order, line discount, GST (CGST+SGST or IGST), round-off, `amount_in_words`, Indian financial-year quote numbers. **100% branch coverage** plus Hypothesis property tests (totals always add up, round-off within 50 paise, more quantity never raises the unit price)
- [x] Quote agent: slot filling against the owner's requirement schema (at most 2 questions per turn, values validated by code, "don't know" uses defaults), then matching to catalogue items. The model never produces a price: quantities are converted and priced by code
- [x] Quote service: create (unpriced lines flagged for the owner), edit before approval (engine recomputes), approve (freezes the PDF, messages the customer the total), reject, mark accepted; PDF with reportlab
- [x] Leads: rule-based score (documented in `orchestrator/leads.py`) and forward-only stages; events logged; accepting a quote wins the lead
- [x] API: quotes (list, detail, edit, approve, reject, accept, PDF), business profile `GET/PUT /tenant`, pricing rules, requirement schemas
- [x] Dashboard: Quotes (review, edit rupees as paise, approve, PDF), Business profile settings, quotation link in chat
- [x] Seeds: printing and photography now come with pricing rules, requirement schemas and a demo GSTIN profile
- [ ] Not built yet: Leads page and kanban (Phase 3), pricing-rule and requirement-schema screens (the API and seeds exist), quote scenarios in MunimBench, a real-model run of the quote flow (needs provider keys)

### Phase 2 acceptance (BUILD_PLAN.md section 15)

| Criterion | Result |
|---|---|
| Printing conversation ends in a PDF with hand-calculated totals | `test_printing_conversation_ends_in_the_hand_calculated_quote`: "500 visiting cards, matt lamination" gives 5 x Rs 235 + 5 x Rs 45 = Rs 1,400, GST Rs 252, total **Rs 1,652.00**. The customer is told nothing about price until the owner approves. |
| Photography conversation likewise | `test_photography_conversation_ends_in_the_hand_calculated_quote`: wedding 2 days + video = Rs 1,10,000, GST Rs 19,800, total **Rs 1,29,800.00**; PDF shows the amount in words |
| Owner approves and the customer receives it | approval writes a message with the total and the quotation link (`quote_id`); verified in Docker and a browser run (priced the last line, approved, lead moved to "quoted") |
| Model cannot affect a price | `test_made_up_items_bad_addons_and_prices_from_the_model_are_ignored`: invented SKUs, unreadable quantities and "price" fields change nothing; unpriced lines block approval |

The conversations use a scripted model, so these prove the logic around it, **not how well a real model
extracts requirements or picks items**. That needs a real-model run (OpenRouter, Groq or Gemini keys).

Commands run: `cd backend && uv run pytest` (286 passed, 96% coverage; `pricing/` 100%),
`uv run ruff check . ../benchmark`, `uv run ruff format --check . ../benchmark`, `uv run mypy` (strict, clean);
`cd dashboard && pnpm lint && pnpm typecheck && pnpm test` (30 passed) `&& pnpm build`;
`docker compose up -d --build` (migration `0003` applied on top of existing data), `python -m seeds.load`, and a
browser run: Quotes list, detail with the Rs 1,652.00 breakdown, priced the open line, approved, PDF downloaded.

## Phase 3 — WhatsApp + voice + handoff

- [x] Migration `0004`: `channel_accounts` (token Fernet-encrypted), message delivery and voice columns with a unique `(tenant_id, external_id)` index, `follow_ups`. API `GET/PUT/DELETE /channels/whatsapp` (owner-only writes, token never returned)
- [x] WhatsApp adapter (`app/channels/`): webhook verification, constant-time HMAC check of the raw body, defensive parsing (text, voice, statuses), text and PDF-document sending, two-step media download with a size cap
- [x] Idempotent inbound (a duplicate webhook stores one message), routing by phone number id, delivery statuses that only move forward, one `deliver_message` job for every outbound path, retries and dead letters from the existing queue, 24-hour window enforced (templates not built)
- [x] Voice notes: local `faster-whisper` transcriber; the transcript is treated like typed text; low confidence asks the customer to confirm; empty or failed asks for text
- [x] Live inbox: customer, preview, take over, staff reply (also takes over), hand back to AI, delivery status per message; the AI is silent while a person owns the chat
- [x] Follow-up drafts: deterministic, one per unanswered quote; the owner sends, edits or dismisses; worker scheduler tick every 10 minutes
- [x] Dashboard: inbox actions and delivery marks, WhatsApp connection form, Follow-ups page
- [ ] Not built: owner WhatsApp notifications and message templates (both need Meta-approved templates, see DECISIONS), customers who hid their phone number (WhatsApp usernames)
- [ ] Not verified: a real Meta test number end to end, and `faster-whisper` on real Hindi/Gujarati audio (the model is a large download; tests use a fake)

### Phase 3 acceptance (BUILD_PLAN.md section 15)

| Criterion | Result |
|---|---|
| Hinglish voice note to approved PDF on WhatsApp | `test_voice_note_to_approved_quotation_pdf_delivered_on_whatsapp`: a signed voice-note webhook, transcript, requirements, quote created (the customer is told only that a quote is coming), the owner approves, the PDF is uploaded and sent as a WhatsApp document with the engine's total (Rs 1,652.00) in the caption. Fake Meta and fake speech model: this proves our side, **not Meta's or Whisper's real behaviour** |
| Duplicate webhooks do not duplicate messages | `test_a_webhook_delivered_twice_is_stored_and_answered_once`; the same id in two businesses is not a duplicate |
| A complaint stops AI replies | `test_a_complaint_hands_over_and_the_ai_stays_silent_afterwards`: the next customer message gets no model call and no reply |
| Bad signature refused | `test_a_webhook_with_a_bad_or_missing_signature_is_refused`, plus unit tests for a tampered body, wrong secret and no secret |
| Running stack | `docker compose up -d --build` (migration `0004` applied) and a signed webhook from a script: bad signature 403, good 200, duplicate 200, the inbox shows the customer, the worker handed off (no model keys) and tried the real Graph API, which refused the fake token, so the message shows `failed` with `OAuthException 190` |

Commands run: `cd backend && uv run pytest` (356 passed, 97% coverage, `pricing/` 100%), `uv run ruff check . ../benchmark`,
`uv run ruff format --check . ../benchmark`, `uv run mypy` (strict, clean); `cd dashboard && pnpm lint &&
pnpm typecheck && pnpm test` (39 passed) `&& pnpm build`; the Docker run above.

## Phase 4 — Benchmark, red team, replay

- [x] MunimBench v0.2: **367 items** (was 100) in 5 languages: a price question for every catalogue item in every language, every FAQ asked another way, availability, things the shops do not sell, greetings, order status, complaints, requests for a person, haggling, off-topic and spam, 23 prompt-injection attempts. Made by `benchmark/generate_items.py` (wording by hand, labels attached from the seed data). CI mode runs 279 of them at 100% price accuracy and 0 hallucinated amounts; the oracle baseline for replay is re-saved with 279 items. Datasheet updated, including that the Hindi/Gujarati wording is AI-drafted and needs a native review.
- [ ] Still open: ~50 audio clips (deferred by the owner), quote-conversation scenarios (multi-turn)
- **Retrieval by language** (oracle model, real multilingual embeddings, `reports/oracle-local.md`, 367 items): the right FAQ or product reaches the model for 98% of English, 96% Hindi (Devanagari), 94% Hinglish, 93% Gujarati (script) and 91% Gujlish questions, 94.7% overall. **Correction:** an earlier version of this line said Hindi and Gujarati script were only about 65%. That was wrong: the benchmark database still held fake-embedder vectors from a previous CI-style run, so the real embedder was never searched. `prepare()` now clears the vectors every run, with a test.
- **English restatement for search** (router field `search_query_en`, searched together with the question): on the Hindi and Gujarati FAQ questions, real Groq router, clean database, one run: Hindi 15/16 to 16/16, Gujarati 12/15 to 15/15, four fixed and none made worse; 3 items skipped by rate limits. A small sample, so a modest real gain, not a proven one.
- Product fixes the dataset prompted: a greeting now gets a fixed welcome instead of "I'll confirm with the team" plus a bogus knowledge gap and lead; an order-status question goes to a person (there is no order system to look it up in).
- [x] First real-model run (Groq `gpt-oss-20b` router, `gpt-oss-120b` for the rest; an evenly spread sample of 40 of the 100 items, local multilingual embeddings): price accuracy 95.0%, **0 hallucinated amounts**, groundedness 90.6%, handoff 95.0%, intent 72.5% (`benchmark/reports/groq-gpt-oss-sample40.md`). The run found two real problems, now fixed: the model put item ids in the wrong citation list (correct answers looked ungrounded) and repeated prices. One run, one model, no OpenRouter (its free models answered 429), so it is a first signal, not a leaderboard. Groq's free tier allows about 8,000 tokens/minute per model, so a full run takes over an hour.
- [x] Looked into the 72.5% intent score: 9 of the 11 mismatches send the message to the same place (policy / availability / product_info / general_faq / pricing all go to Knowledge; spam and off_topic both stop at the off-topic reply), at confidence 0.9 or more, so the gold labels are debatable rather than the model wrong. One real misroute: "Can I get a sample first?" went to the quote flow. The benchmark now reports `route_accuracy` (the metric that decides what the customer sees) and `model_errors` (items where a model call failed). The two Groq 400s were `json_validate_failed` (the model broke JSON mode); the client now asks that provider again once. A re-run the same day was **not valid**: Groq's free quota ran out (`rate_limit_exceeded`, 22 of 40 items had a failed model call), which the new `model_errors` count showed at once. A clean run needs a fresh quota or a second provider (a Gemini key).
- [ ] Eval runner + multi-model leaderboard
- [x] Adversarial price suite (`make adversarial`, `benchmark/adversarial.py`): 1,384 price attacks, 100 leak attacks and 51 honest replies; the first run found **23 of 35 hand-written disguises getting through** (e.g. `200₹`, "two hundred rupees", "do sau rupaye", "price is 200", `$2.50`, `Rs 25,0` read as 250), so `app/agents/amounts.py` was rewritten; now 0 / 1,384 missed, 0 leaks, 0 honest replies blocked, and the old misses are replayed from `benchmark/regressions/price_attacks.txt`. Runs in `pytest`, so CI enforces it. Not yet run against a real model.
- [x] Prompt versioning + `make replay` + CI gate on price accuracy: every prompt has a `<name>@<hash>` version (also on `agent_runs`); `benchmark/replay.py` diffs a run against `benchmark/baselines/oracle.json` (87 items) and fails on a regression, a disallowed amount, a price-accuracy drop or a dropped item. `tests/integration/test_replay.py` proves a responder prompt that stops passing the price lines is caught (price accuracy falls, the gate says FAIL) and a wording-only edit passes but is reported. Oracle-only for now: wording quality needs a baseline from a real model.
- [x] Cost / latency report from `agent_runs`: every run now stores its cost at list price (`app/llm/costs.py`, integer micro-dollars; only models with a checked price, today the two Groq `gpt-oss` models, anything else is reported as unpriced, never guessed). `app/tools/metrics.py` gives per agent and model: calls, errors, tokens, cost, p50/p95 latency, plus cost per customer turn and p50/p95 first-response time; tenant-scoped, tested. `make cost` prints it for the benchmark tenants. **No real numbers published yet**: the real-model run lost its data and needs a fresh Groq quota (the oracle run only proves the report works). Not measured: cache hit rate (there is no cache) and fallback rate (the chain does not record which provider was tried first).

## Phase 5 — Pilot + release

- [x] Rate limits (`app/core/ratelimit.py`, in-process sliding window, no Redis): login 10/min and registration 5/hour per address, refresh 30/min, 300 calls/min per business, 30 playground messages/min, bad webhook signatures shut an address out after 20/min, and one customer chat past 30 messages in 10 minutes is stored but not answered (protects the shared model quota). Upload size and type checks already existed (content sniffing, size cap). Proxy header only trusted when configured.
- [ ] Metrics page (the queries exist in `app/tools/metrics.py`; no dashboard page yet)
- [ ] Self-host guide (Compose + Cloudflare Tunnel), nightly `pg_dump`
- [x] Privacy notice template (`docs/PRIVACY.md`) + owner-only customer search, export and permanent erasure (`/customers`): removes the customer, chats, leads, quotes and PDFs, follow-ups, the `agent_runs` that hold their words and the knowledge gap that quotes them; keeps other customers; tested. Not legal advice; needs a lawyer's review.
- [ ] Pilot with 2–3 real businesses; owner guide
- [ ] README with architecture diagram, demo, leaderboard and reliability numbers

## Log

- 2026-11-15 — Phase 0 implemented. See acceptance table above.
