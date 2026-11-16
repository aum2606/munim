.PHONY: dev migrate revision seed test test-be test-fe lint fmt eval adversarial replay replay-save

dev: ## full stack: api, worker, postgres(pgvector), dashboard
	@test -f .env || cp .env.example .env
	docker compose up --build

migrate:
	cd backend && uv run alembic upgrade head

revision: ## make revision m="message" (autogenerate, then review the file by hand)
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

seed: ## create the demo businesses (the stack must be running); prints their logins once
	docker compose exec api python -m seeds.load

eval: ## MunimBench. CI mode by default; add LLM=real EMB=local with EVAL_USE_REAL_LLM=1 for a real model
	cd backend && PYTHONPATH=.:.. uv run python -m benchmark.run --llm $(or $(LLM),fake) --embedder $(or $(EMB),fake)

adversarial: ## Adversarial price suite: every wrong amount must be blocked (no keys, no database)
	cd backend && PYTHONPATH=.:.. uv run python -m benchmark.adversarial

replay: ## Replay the benchmark against benchmark/baselines/<FROM>.json; fails on any regression (needs DATABASE_URL)
	cd backend && PYTHONPATH=.:.. uv run python -m benchmark.replay --from $(or $(FROM),oracle)

replay-save: ## Accept the current prompts and code as the new baseline
	cd backend && PYTHONPATH=.:.. uv run python -m benchmark.replay --from $(or $(FROM),oracle) --save

test: test-be test-fe

test-be:
	cd backend && uv run pytest

test-fe:
	cd dashboard && pnpm test

lint:
	cd backend && uv run ruff check . ../benchmark && uv run ruff format --check . ../benchmark && uv run mypy
	cd dashboard && pnpm lint && pnpm format:check && pnpm typecheck

fmt:
	cd backend && uv run ruff format . ../benchmark && uv run ruff check --fix . ../benchmark
	cd dashboard && pnpm format
