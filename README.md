# Munim

Multi-tenant AI employee for Indian small businesses. Phase 1 includes catalogue import,
document and FAQ ingestion, grounded web chat, a dashboard playground with agent traces,
and a read-only inbox. See BUILD_PLAN.md for subsequent phases.

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

## Development and checks

Backend commands load the repository-root `.env`; exported variables take precedence.
`make test` runs backend and frontend tests and enforces 100% pricing branch coverage.
`make lint`, `make build`, `make migrate` and `make eval` run the other main checks.
Integration and golden conversation tests require Docker for isolated PostgreSQL and
Redis testcontainers. Tests use FakeLLM/FakeEmbedder and block external HTTP; provider
contract tests use MockTransport. `make eval` includes 25 seeded conversations and
injection/price guardrail cases. The opt-in real-model evaluation harness is Phase 6.

`make e2e` runs Chromium flows at desktop and 375px mobile widths. With Compose running,
install Chromium using `pnpm exec playwright install chromium`, then run `make e2e`.
For a host API process use `uv run --directory backend uvicorn app.main:create_app
--factory --port 18000`; also start the worker and built widget server for chat flows.

On Windows, install GNU Make or run the commands from Makefile directly. Use
`pnpm.cmd` if PowerShell blocks `pnpm.ps1`. Compose uses local database and Redis ports
57432 and 56379. Production deployment and hardening are scheduled in Phase 6.

See PROGRESS.md for validation results and DECISIONS.md for design choices.
