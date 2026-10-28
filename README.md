# Munim

Multi-tenant AI employee for Indian small businesses. Phase 2 includes catalogue import,
document and FAQ ingestion, grounded web chat, requirements collection, GST quotations
with owner approval and PDF delivery, a playground with agent traces, and a read-only inbox. See BUILD_PLAN.md for subsequent phases.

## Run locally

Install Docker Desktop, Python 3.12 + uv, Node 22 + pnpm 10.33.2, and GNU Make.
Copy `.env.example` to `.env` and set `SECRET_KEY` to a randomly generated value
(at least 32 characters). `make setup` installs locked development dependencies.
`make dev` builds the services, migrates Postgres, and starts the API, worker,
dashboard and widget. Keep the worker running for ingestion and chat replies.

- Dashboard: http://localhost:5173
- API documentation: http://localhost:18000/docs
- Readiness: http://localhost:18000/ready
- Widget preview: http://localhost:5174

Create an account in the dashboard, then upload a catalogue in Knowledge, review the
column mapping and parsed prices, and confirm the import. Add FAQs or PDF/DOCX/TXT
documents and wait for Ready status. Use Playground to try questions and inspect
redacted agent traces. Knowledge also shows unanswered questions and the installation
snippet for your website. The widget runs in an isolated Shadow DOM and streams
conversation updates over SSE.

Passwords require at least 12 characters. Dashboard sessions stay in browser memory;
reloading signs you out. Access tokens refresh while the page is open. Sign out revokes
the refresh token; existing access tokens expire within 15 minutes.

## Demo businesses and model modes

Set `DEMO_SEED_PASSWORD` in `.env` to a unique demo password of at least 12 characters,
then run `make seed`. Demo owners are `electronics@example.com`,
`photography@example.com` and `printing@example.com`. Each workspace has four catalogue
entries and several FAQs. Re-running the seed updates demo content without duplicating
it or changing an existing owner's password. These are synthetic local demo accounts.

The default `LLM_PROVIDER=fake` and `EMBEDDING_PROVIDER=fake` run offline. Fake mode
supports deterministic demonstrations; it does not establish real-model retrieval
quality. To connect a provider, configure the documented model and API variables in
`.env.example`; embeddings must have 1024 dimensions. Outbound prices always come from
the catalogue pricing tools. Responses conservatively copy trusted facts; unsupported
questions create knowledge gaps and receive a holding reply.

## Requirements and quotations

In Quotes, set the business GSTIN, supplier state, address and optional PNG/JPEG logo.
Set quote validity and terms there too. GST-bearing quotes need the supplier GSTIN and
state before sending. Profile/settings changes apply to new quotes; saving a revised
pending quote refreshes its business details, terms and validity.

A customer can request a quote in the widget or Playground. Requirements are saved on
the conversation and lead. The assistant asks at most two missing questions per turn;
explicit unknown answers use configured defaults. The five default schemas cover
printing, photography, interior, repair and electronics; owners can update them through
the requirement-schemas API.

Quotes shows pending approvals and recent history. Review the PDF, select catalogue
products, edit quantities/options or place of supply, then Save & recalculate. Approval
uses the reviewed version; stale edits are rejected. Approve & send delivers one PDF
message to the same customer conversation. Download requires that conversation's bearer
session. Sent quotes cannot be edited. Auto-send is off by default; enabling it sends
only fully priced quotes strictly below the configured INR limit in open AI chats.

Catalogue defaults and pricing rules are available through the owner APIs in the API
documentation. A base-price option uses `attributes.default_<slot>` (pipe-separated
accepted values); other options need an add-on rule. Packs use `attributes.pack_size`.
Unmapped products or unpriced options remain pending owner pricing and block sending.
An owner can add priced catalogue entries through import, then revise the quote.

For the offline demo, start a printing quote with
`quote; item=visiting cards; quantity=500; sides=double-sided`, then answer
`size=unknown; material=unknown; colour=unknown; finishing=unknown; deadline=2026-12-20`.
For photography start with `quote; event_type=wedding; days=2; deliverables=photo+video`,
then `date=2026-12-20; city_venue=Ahmedabad; hours=unknown; crew_size=unknown`.
The synthetic seed prices produce totals of INR 3,245 and INR 1,06,200 respectively.
Fake mode accepts these explicit key/value answers; this demonstrates the deterministic
flow, not real-model language quality. Configure your own business tax details before
using quotations outside the synthetic demo.

## Leads and the live Inbox

Every processed conversation updates a lead in a separate background job. Leads shows
stages, scores, requirements, assigned staff and an audited timeline. Saving a manual
stage protects it from automation; Resume automatic stages releases that override.
Quote delivery moves an automatic lead to Quoted; accepted/rejected quotes move it to
Won/Lost. Estimated values come from saved quote totals.

A complaint or request for a human opens a handoff and stops AI replies. Inbox supports
Take over, Use assist mode and Return to AI. Human mode lets staff reply; assist mode
creates private suggestions that staff review and approve. Changing mode consumes older
queued inbound, so Return to AI starts with the customer's next message. Staff messages
still pass the price and discount checks against current catalogue/quote tool results.
Notifications show open handoffs and pending follow-ups, with live bearer-authenticated
SSE updates. Reconnection refreshes expired access tokens.

In Leads, owners configure no-reply, quote reminder and dormant re-engagement windows.
The worker scans every 15 minutes and creates drafts. Approve & send rechecks whether
the customer has replied and whether the conversation is still eligible; the scheduler
never sends customer messages itself. Delivery is web-only until Phase 4 adds channel
adapters and approved templates. Working hours can be configured through
`PUT /api/v1/tenant/business-hours`, for example
`{"hours":{"monday":["09:00","18:00"]}}`. Days not configured are closed;
empty hours make no out-of-hours claim. Holding replies use the tenant timezone.

## WhatsApp setup and live acceptance

Phase 4 code includes signed webhooks, encrypted per-tenant accounts, native quote PDF
uploads, interactive reply buttons, static template follow-ups and durable delivery
status/reconciliation. The automated acceptance uses a fake Meta HTTP transport;
a real Meta test-number run is still pending because no test number is configured.

1. Create/register your WhatsApp test number in Meta and add an authorized test recipient.
   Use a token from the same Meta app as your webhook configuration, with
   `whatsapp_business_messaging` and `whatsapp_business_management` permissions.
2. Run `make channel-key` once and put its output in `CREDENTIALS_ENCRYPTION_KEY`
   in `.env`. Keep this key private and stable; changing it requires reconnecting
   existing accounts. Set `WHATSAPP_APP_SECRET`, a random `WHATSAPP_VERIFY_TOKEN`,
   and a currently supported `WHATSAPP_API_VERSION` in the form `vNN.0`.
3. Set `PUBLIC_API_URL` to your public HTTPS API origin and restart API/worker services.
   In Meta configure the callback shown in Dashboard > WhatsApp, normally
   `https://your-api.example/api/v1/webhooks/whatsapp`, with the same verification token.
   Enable the `messages` webhook field. Localhost alone cannot receive Meta callbacks.
4. In WhatsApp settings enter the phone-number ID, WABA ID and token. Connection verifies
   the phone belongs to that WABA and subscribes the token's app to WABA webhooks.
   Credentials are encrypted and never returned by the API. Reconnect with the same
   IDs to rotate a token. Disabling the account stops new processing/sends while
   delivery status callbacks continue to be recorded.
5. Sync approved templates from Meta. Follow-ups support static BODY-only text templates
   without variables or money; unsupported templates are shown but unavailable. Record
   the customer's opt-in and evidence in Inbox before approving a template follow-up.
   Review the exact template text in Leads. STOP revokes opt-in and stops automation.

Free-form text, reply buttons and quote documents are allowed only while the customer's
24-hour window remains open. The original provider timestamp controls this window;
webhook replay does not reopen it. Expired quotes and windows block delivery. Media
inbound is retained as metadata/caption and routed to staff; automatic OCR/ingestion is
not part of this phase. Staff can download the original attachment from Inbox through
an authenticated, size-bounded server endpoint (8 MiB default); provider tokens and
temporary media URLs are never exposed to the browser.

WhatsApp deliveries are durably queued in the same transaction as message approval.
Quote/follow-up sent state means released to the channel; WhatsApp > Delivery history
shows actual queued/accepted/delivered/read state. Workers scan every five seconds,
retry explicit transient rejections with bounded backoff/Retry-After, and record failed
or blocked deliveries for owner review. Ambiguous sends and interrupted workers are
marked uncertain and hold later conversation deliveries. Check Meta before explicitly
confirming a provider message ID or confirming a message was not sent and retrying.
The system does not claim exactly-once delivery across an ambiguous network failure.

For live acceptance, send the seeded printing enquiry from the authorized test recipient,
complete requirements, approve the quote in the dashboard, and verify the PDF arrives
as a WhatsApp document. Then replay the signed webhook (or inspect Meta's duplicate
retry) and confirm that message/quote counts do not grow. Run an out-of-window and STOP
check before connecting real customers. Optional owner alerts on WhatsApp are deferred;
owner handoff/quote notifications remain in the dashboard.

Official references: [Meta's Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/overview),
[WABA subscription](https://www.postman.com/meta/whatsapp-business-platform/request/c1ai24q/subscribe-to-your-waba),
[document delivery](https://www.postman.com/meta/whatsapp-business-platform/request/zjtbdpz/send-document-message-by-id),
and [WhatsApp messaging policy](https://business.whatsapp.com/policy).

## Insights and weekly digest

Open **Overview** for enquiries over time, grounded catalogue interest, intent mix,
quote statuses, channels, first reply time, AI resolution and current open knowledge gaps.
Choose a rolling 7/30/90-day window or the current IST week/month. Every chart has an
expandable exact-value table, including on phones. Missing response/resolution data is
shown as unavailable instead of zero.

Open **Insights → Ask Munim** and try:

- "Who hasn't responded this week?"
- "What are people asking about most this month?"
- "How many quotes were accepted?"

The reasoning model selects one of twelve fixed analytics tools. All queries run through
tenant-scoped repositories, and Python renders the returned counts/tables/chart specs;
the model cannot submit SQL or change numbers. Unsupported questions create a knowledge
gap and receive the standard confirmation response. Fake-model mode supports these demo
questions; offline golden tests use synthetic seeded facts. Real-model answer quality
still needs the opt-in evaluation work scheduled in Phase 6.

Enquiries count the first inbound per conversation. The quote funnel and accepted count
show **current statuses for quotes created in the selected period**, not a historical
status-transition chart. First-response time is measured at message persistence and
excludes unanswered conversations; it does not measure WhatsApp delivery latency.
AI resolution is the share of closed conversations without a handoff within the enquiry
cohort. Item counts cover grounded catalogue references and quotation lines since event
tracking began; older activity is not inferred or backfilled. Open gaps are a current
snapshot. The page includes these definitions.

The worker publishes a dashboard digest on **Monday 09:00 IST**, covering the preceding
Monday-to-Monday week. Worker startup catches up the latest due week. A unique tenant/week
key prevents duplicate digests on retries; viewing a digest does not regenerate it.
Keep the worker running to receive scheduled digests. Optional delivery to the owner's
WhatsApp/email remains deferred until recipient/consent/template setup is available.
The Phase 4 live Meta test remains pending separately, as authorized by the user.

## Development and checks

Backend commands load the repository-root `.env`; exported variables take precedence.
`make test` runs backend and frontend tests and enforces 100% pricing branch coverage.
`make lint`, `make build`, `make migrate` and `make eval` run the other main checks.
Integration and golden conversation tests require Docker for isolated PostgreSQL and
Redis testcontainers. Tests use FakeLLM/FakeEmbedder and block external HTTP; provider
contract tests use MockTransport. `make eval` includes 25 Phase 1 conversations, requirement extraction cases, two
Phase 2 quotation conversations, Phase 3 handoff/stage/follow-up acceptance, Phase 4 fake-Meta quotation delivery and expired-window checks, and the three Phase 5 analytics acceptance questions. The full suite also checks injected prices, approval
races, stale edits, expiry, tenant isolation and auto-send limits. The opt-in real-model evaluation harness is Phase 6.

`make e2e` runs Chromium flows at desktop and 375px mobile widths. With Compose running,
install Chromium using `pnpm exec playwright install chromium`, then run `make e2e`. The fourteen flows include analytics/Ask Munim, approving a quotation and downloading
its PDF, complaint handoff, private assist approval and return to AI with a real embedded
widget on mobile and desktop.
For a host API process use `uv run --directory backend uvicorn app.main:create_app
--factory --port 18000`; also start the worker and built widget server for chat flows.

On Windows, install GNU Make or run the commands from Makefile directly. Use
`pnpm.cmd` if PowerShell blocks `pnpm.ps1`. Compose uses local database and Redis ports
57432 and 56379. Production deployment and hardening are scheduled in Phase 6.

See PROGRESS.md for validation results and DECISIONS.md for design choices.
