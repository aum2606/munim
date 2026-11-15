FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY seeds ./seeds

# Run as an unprivileged user.
RUN useradd --system --no-create-home munim \
 && mkdir -p /data/uploads /data/models \
 && chown -R munim /app /data
USER munim
# No home directory for this user, so point model-download caches somewhere writable.
ENV PATH="/app/.venv/bin:$PATH" HF_HOME=/data/models/hf XDG_CACHE_HOME=/data/models/xdg

EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
