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

## Development and checks

Backend commands load the repository-root `.env`; exported variables take precedence.
`make test` runs backend and frontend tests and enforces 100% pricing branch coverage.
`make lint`, `make build`, `make migrate` and `make eval` run the other main checks.
Integration and golden conversation tests require Docker for isolated PostgreSQL and
Redis testcontainers. Tests use FakeLLM/FakeEmbedder and block external HTTP; provider
contract tests use MockTransport. `make eval` includes 25 Phase 1 conversations, requirement extraction cases, and two
Phase 2 quotation conversations. The full suite also checks injected prices, approval
races, stale edits, expiry, tenant isolation and auto-send limits. The opt-in real-model evaluation harness is Phase 6.

`make e2e` runs Chromium flows at desktop and 375px mobile widths. With Compose running,
install Chromium using `pnpm exec playwright install chromium`, then run `make e2e`. The eight flows include approving a quotation and downloading
its PDF from a real embedded widget on mobile and desktop.
For a host API process use `uv run --directory backend uvicorn app.main:create_app
--factory --port 18000`; also start the worker and built widget server for chat flows.

On Windows, install GNU Make or run the commands from Makefile directly. Use
`pnpm.cmd` if PowerShell blocks `pnpm.ps1`. Compose uses local database and Redis ports
57432 and 56379. Production deployment and hardening are scheduled in Phase 6.

See PROGRESS.md for validation results and DECISIONS.md for design choices.
