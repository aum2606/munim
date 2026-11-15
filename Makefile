.PHONY: dev migrate revision test test-be test-fe lint fmt

dev: ## full stack: api, worker, postgres(pgvector), dashboard
	@test -f .env || cp .env.example .env
	docker compose up --build

migrate:
	cd backend && uv run alembic upgrade head

revision: ## make revision m="message" (autogenerate, then review the file by hand)
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

test: test-be test-fe

test-be:
	cd backend && uv run pytest

test-fe:
	cd dashboard && pnpm test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd dashboard && pnpm lint && pnpm format:check && pnpm typecheck

fmt:
	cd backend && uv run ruff format . && uv run ruff check --fix .
	cd dashboard && pnpm format
