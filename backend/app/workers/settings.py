from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import Settings
from app.workers.tasks import ingest_document, process_message, update_lead


async def heartbeat(ctx: dict[str, Any]) -> str:
    """A minimal diagnostic task keeps the foundation worker runnable."""
    return "ok"


class WorkerSettings:
    functions: ClassVar[list[Callable[..., Awaitable[Any]]]] = [
        heartbeat,
        ingest_document,
        process_message,
        update_lead,
    ]
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)

    max_tries = 100
    job_timeout = Settings().llm_timeout_s * 10 + 120
