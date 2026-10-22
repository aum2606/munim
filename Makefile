.PHONY: dev setup migrate revision seed test test-be test-fe e2e lint fmt eval build
setup:
	uv sync --directory backend --frozen
	pnpm install --frozen-lockfile
dev:
	docker compose up --build
migrate:
	uv run --directory backend alembic upgrade head
revision:
	uv run --directory backend alembic revision --autogenerate -m "$(m)"
seed:
	uv run --directory backend python -m seeds
test: test-be test-fe
test-be:
	uv run --directory backend pytest --cov=app.pricing --cov-branch --cov-fail-under=100
test-fe:
	pnpm test
e2e:
	pnpm e2e
lint:
	uv run --directory backend ruff check .
	uv run --directory backend ruff format --check .
	uv run --directory backend mypy app
	pnpm lint
fmt:
	uv run --directory backend ruff format .
	uv run --directory backend ruff check --fix .
	pnpm fmt
build:
	pnpm build
eval:
	uv run --directory backend pytest tests/evals
