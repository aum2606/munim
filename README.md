# Munim

Multi-tenant AI employee for Indian small businesses. Phase 0 provides the backend,
authentication, audited model interfaces, and dashboard shell. Domain features follow BUILD_PLAN.md.

## Run locally

Install Docker Desktop, Python 3.12 + uv, Node 22 + pnpm 10.33.2, and GNU Make.
Copy `.env.example` to `.env` and set `SECRET_KEY` to a randomly generated value
(at least 32 characters). `make dev` builds all services, migrates Postgres, and starts
API/worker/dashboard/widget. Dashboard: http://localhost:5173; API docs:
http://localhost:18000/docs; readiness: http://localhost:18000/ready.

Use the dashboard's Create account link to register a business and owner. Passwords
require at least 12 characters. Sessions stay in browser memory; reloading signs you
out. Short-lived access tokens refresh automatically while the page is open. Sign out
revokes the refresh token; existing access tokens expire within 15 minutes.

## Development and checks

`make setup` installs locked dependencies. Backend commands load the repository-root
`.env` automatically; exported environment variables take precedence.
`make migrate`, `make test`, `make lint`, `make build`, and `make e2e` are the primary
checks. Start the API separately for Playwright: `uv run --directory backend uvicorn
app.main:create_app --factory --port 18000`. `pnpm exec playwright install chromium` installs its
browser. Integration tests create an isolated Postgres testcontainer and apply the
actual Alembic migration. They require a working Docker engine and never use SQLite.
Tests block external HTTP; provider tests use httpx MockTransport. `make eval` currently
checks offline model foundations; golden conversations and real-model opt-in arrive
in Phase 6. `make seed` reports Phase 0 status; full demo content arrives in Phase 1.

On Windows, use GNU Make from a terminal where it is installed, or run the commands
listed in Makefile directly (`pnpm.cmd` if PowerShell blocks `pnpm.ps1`). Docker Compose
reads `.env` at the repository root. Development DB credentials in Compose are local
examples; production configuration is scheduled in Phase 6.

See PROGRESS.md for exact validation results and DECISIONS.md for design choices.
