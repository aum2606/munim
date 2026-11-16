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

## Phase 2

- **2026-11-16 — Quote PDFs use reportlab, not WeasyPrint (deviation from BUILD_PLAN.md section 4).**
  WeasyPrint needs GTK/Pango system libraries, which the Windows dev machines here do not have, so the
  PDF could not be tested locally. reportlab is pure Python and runs everywhere. Quote text is escaped
  before it reaches the PDF, so customer or owner text can never be interpreted as markup.
- **2026-11-16 — PDFs print "Rs. 1,652.00", not the rupee sign.** The built-in PDF fonts have no rupee
  glyph and bundling a font file would add an asset for no gain. `format_inr` still produces the sign
  everywhere else.
- **2026-11-16 — The model proposes items and quantities only; code does all quantity maths and pricing.**
  The mapping step returns SKU, pieces, optional width/height and add-on codes. `billable_qty` turns pieces
  into priced units ("per 100" means 500 cards is 5 units; "per sq ft" multiplies the size), every SKU
  and add-on code is checked against the catalogue, and any "price" field the model adds is ignored.
  An item that cannot be priced becomes a zero-price line flagged `needs_owner_pricing`, and approval is
  blocked until the owner prices it.
- **2026-11-16 — "per N" is a pack size only when N counts pieces.** "per 100" and "per 100 pcs" are pack
  sizes; "per 2 days" or "per event" are not (a 2-day wedding package is one unit). A unit written
  another way is treated as one unit, so check imported units.
- **2026-11-16 — Customers never see a price before the owner approves.** While a quote is prepared the
  customer is told the team will send it; on approval a message with the total and the quotation link
  is added to the chat (sender `staff`). The price guardrail still checks every question the assistant asks.
- **2026-11-16 — Tax rules.** Same state, or either state unknown, means CGST + SGST; otherwise IGST. The
  seller's state comes from the GSTIN in the business profile. Each half of intra-state tax is rounded on
  its own, so CGST + SGST can differ from IGST by a paisa per rate (a property test bounds it). The total
  is rounded to the nearest rupee, with the round-off shown. GSTIN is checked for format only, not for
  existence.
- **2026-11-16 — Pricing rules are tiers, add-ons and minimum order, stored as JSON per item or category.**
  Tiers give a fixed unit price or a percent off (percent as a Decimal string, never a float). An add-on
  becomes its own line, taxed like the item it belongs to. Rules are validated when saved; there is no
  screen for them yet (API and seeds only).
- **2026-11-16 — Quote numbers use an upsert counter per tenant per financial year.** `Q/2026-27/0001`;
  concurrent quotes cannot collide (tested with 8 at once) and April starts a new sequence.
- **2026-11-16 — An active quote conversation keeps short replies in the flow.** While requirements are
  being collected, an answer like "500" stays with the quote even if the router is unsure or calls it
  off-topic. Complaints, requests for a person and haggling still go to a human.
- **2026-11-16 — Lead stage and score are rule-based, never model-decided.** Stages only move forward;
  won, lost and dormant are never changed automatically; only an accepted quote wins a lead. The score
  formula is in the docstring of `lead_score`. The router's sentiment is the only model input (plus 5 or
  minus 10 points).
- **2026-11-16 — NEEDS REVIEW: unknown "don't know" answers do not block a quote.** A slot the customer
  skips gets the schema default, or "not specified" if there is none, so the quote is still prepared and
  the owner sees the gap. Decide whether some details (a deadline, a size) should be mandatory.
- **2026-11-16 — Seller state unknown means CGST + SGST.** A business that has not entered a GSTIN yet
  still gets quotes, taxed as same-state. The settings page says the GSTIN decides this.
- **2026-11-16 — Provider endpoints were checked against official docs on 2026-11-16** (Groq, OpenRouter
  and Gemini OpenAI-compatible URLs are in `.env.example`). Model names and free-tier limits change often
  and some free tiers use prompts to improve products, so they are deliberately not hard-coded.
- **2026-11-16 — The dashboard container now runs pnpm non-interactively (`CI=true`) with its cache outside
  the mounted folder,** after the pnpm cache was committed by mistake in Phase 0.

## Phase 3 — WhatsApp, voice, handoff

- **2026-11-16 — Meta behaviour was checked against the official docs** (links in `app/channels/whatsapp.py`):
  the webhook check echoes `hub.challenge`; POSTs are signed with `X-Hub-Signature-256` (HMAC-SHA256 of the
  raw body, keyed with the app secret); media is fetched in two steps with the same bearer token; a free-form
  reply is allowed for 24 hours after the customer's last message.
- **2026-11-16 — One Meta app for the whole deployment, one number per business.** The verify token and app
  secret are server settings; each business saves only its phone number id and access token
  (`channel_accounts`, token Fernet-encrypted with `CREDENTIALS_ENCRYPTION_KEY`, required in prod; outside
  prod a key is derived from `SECRET_KEY`). The token is write-only: no endpoint returns it. A phone number
  id can belong to one business only. With no verify token or app secret the webhook refuses everything.
- **2026-11-16 — Webhooks are idempotent through a unique `(tenant_id, external_id)` index on messages,**
  not an in-memory check, so a retry or two simultaneous deliveries store one message (a savepoint wraps
  the insert). Delivery statuses only move forward: a late "sent" never undoes "read".
- **2026-11-16 — Every outbound customer message is delivered by one job, created in
  `ChatRepository.add_message`.** AI replies, staff replies, quote approvals and follow-ups all pass through
  it, so no path can forget to deliver. The job is safe to run twice (a message that has Meta's id is never
  sent again); permanent errors (bad token, bad number) mark the message `failed` with Meta's error code,
  temporary ones retry with backoff. An approved quotation goes as a PDF document with the approval text as
  its caption.
- **2026-11-16 — Message timestamps are set in Python, not by the database.** `now()` is the transaction's
  start, so a customer message and our reply stored in one transaction tied and could swap places.
- **2026-11-16 — Message templates are not built, so nothing is sent after the 24-hour window.** Such a
  message is stored as `window_closed` and shown as not sent; the inbox hides the reply box and replying
  through the API returns 409. This also means follow-ups (due after 2 days) cannot be sent from the
  dashboard on WhatsApp: the draft offers "Copy text" and the owner messages the customer themself. Revisit
  when a business has an approved template (`BUILD_PLAN.md` section 3 keeps templates off by default).
- **2026-11-16 — NEEDS REVIEW: owner WhatsApp notifications are not built.** They would message the
  owner's own number, which is outside the 24-hour window unless the owner wrote recently, so they need
  approved templates. The inbox shows who needs a person and refreshes every 10 seconds instead.
- **2026-11-16 — Customers who hid their phone number (WhatsApp usernames) are skipped for now.** Their
  webhooks carry a user id but no phone, and replying needs the `recipient` field. Skipped and logged, not
  stored.
- **2026-11-16 — Voice notes are transcribed locally with faster-whisper** (`STT_MODEL`, default `small`,
  CPU, int8; weights download on first use into `STT_CACHE_DIR`). Confidence is the geometric mean token
  probability, a heuristic. At or above `STT_CONFIDENCE_THRESHOLD` (0.6) the transcript is treated like
  typed text; below it nothing is acted on and the customer is shown what we heard and asked to confirm or
  type; an empty transcript or a failed download asks for text. Fixed replies to a voice note use
  Roman-script Hinglish/Gujlish for Hindi/Gujarati speech and English otherwise; the normal turn still
  detects the real language. NEEDS REVIEW: the confirmation echoes the customer's own words, which can
  contain an amount; it is a fixed reply, not a quote, so it skips the price guardrail.
- **2026-11-16 — A person takes over by button or by replying.** Either sets the chat to human; the
  pipeline then stores new customer messages as handled and says nothing, with no model call. A complaint
  or request for a person already did this in Phase 1. "Hand back to AI" is explicit.
- **2026-11-16 — Follow-up drafts are deterministic and never sent automatically.** A sent quote with no
  customer message since, older than `FOLLOWUP_AFTER_DAYS` (2), gets one fixed localized draft per quote
  (no amount in it). The worker checks every 10 minutes and queues one job per business that needs it.
- **2026-11-16 — `httpx` request logging is switched off.** It logged full URLs, and Meta's media URLs carry
  signed query strings.

## Phase 4 — Red team

- **2026-11-16 — The price guardrail now reads amounts from `app/agents/amounts.py`, and is stricter.** The
  adversarial suite showed the Phase 1 regex only caught an amount with a currency sign or word in the usual
  place. It now also catches: `₹` after the number, `$`/`€`/dollars, "1.2 lakh" and "2 hazaar", a bare number
  next to a price cue ("price is 200", "200 ka rate hai", "200 में हो जाएगा"), numbers spelled out with a
  currency word or a price cue ("two hundred rupees", "do sau rupaye", "બસો રૂપિયા"), and obfuscation (zero-width
  characters, full-width digits, `₨`, `2oo`). Malformed grouping such as `25,0` was read as 250 and is now
  UNREADABLE. Spelled-out and foreign amounts are always UNREADABLE (never equal to a real price), because
  honest replies write prices as digits.
- **2026-11-16 — Quantities, dates, percentages and "per 100" are deliberately not prices,** so "500 cards",
  "3 days", "22 Nov", "18% GST" and "₹250 per 100" pass. The suite's honest set (51 replies, including every
  fixed reply in five languages) and MunimBench both show 0 honest replies blocked.
- **2026-11-16 — NEEDS REVIEW: known limits of the guardrail.** A spelled-out amount with no price cue and no
  currency word ("five hundred") looks like a quantity and is not flagged. Hindi and Gujarati number words are
  a hand-written list (units, tens and multiples), not every number. A translated leak of the system prompt is
  not caught (only the English phrases are). The suite attacks the guardrail with synthetic replies; whether a
  real model produces anything new needs a real-model run (`make eval` with a key).
