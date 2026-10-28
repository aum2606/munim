from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.config import Settings
from app.workers.tasks import (
    deliver_whatsapp,
    dispatch_channels,
    draft_followups,
    ingest_document,
    process_message,
    schedule_followups,
    update_lead,
)


async def heartbeat(ctx: dict[str, Any]) -> str:
    """A minimal diagnostic task keeps the foundation worker runnable."""
    return "ok"


class WorkerSettings:
    functions: ClassVar[list[Callable[..., Awaitable[Any]]]] = [
        heartbeat,
        ingest_document,
        process_message,
        update_lead,
        draft_followups,
        deliver_whatsapp,
    ]
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)

    cron_jobs = [
        cron(schedule_followups, minute={0, 15, 30, 45}, run_at_startup=True),
        cron(dispatch_channels, second=set(range(0, 60, 5)), run_at_startup=True),
    ]

    max_tries = 100
    job_timeout = Settings().llm_timeout_s * 10 + 120
