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
	uv run --directory backend ruff check --config pyproject.toml ../deploy/ops.py
	uv run --directory backend ruff format --config pyproject.toml --check ../deploy/ops.py
	uv run --directory backend mypy --strict ../deploy/ops.py
	pnpm lint
fmt:
	uv run --directory backend ruff format --config pyproject.toml ../deploy/ops.py
	uv run --directory backend ruff format .
	uv run --directory backend ruff check --fix .
	pnpm fmt
build:
	pnpm build
eval:
	uv run --directory backend python -m app.agents.eval_command

.PHONY: channel-key
channel-key:
	uv run --directory backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

.PHONY: prod-config prod-build prod-up backup restore-check
PROD_COMPOSE = docker compose --env-file .env.production -f docker-compose.prod.yml
prod-config:
	$(PROD_COMPOSE) config --quiet
prod-build: prod-config
	$(PROD_COMPOSE) build
prod-up: prod-config
	$(PROD_COMPOSE) up -d --build
backup:
	$(PROD_COMPOSE) run --rm backup /ops-venv/bin/python /ops/ops.py backup
restore-check:
	uv run --directory backend pytest tests/integration/test_restore.py
