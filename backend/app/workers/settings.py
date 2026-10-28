from collections.abc import Awaitable, Callable
from datetime import UTC
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.config import Settings
from app.workers.tasks import (
    cleanup_privacy,
    deliver_whatsapp,
    dispatch_channels,
    draft_followups,
    generate_digest,
    ingest_document,
    process_message,
    schedule_digests,
    schedule_followups,
    schedule_privacy_cleanup,
    update_lead,
)


async def heartbeat(ctx: dict[str, Any]) -> str:
    """A minimal diagnostic task keeps the foundation worker runnable."""
    return "ok"


async def startup(ctx: dict[str, Any]) -> None:
    from app.core.logging import configure_logging

    configure_logging()


class WorkerSettings:
    on_startup = startup
    functions: ClassVar[list[Callable[..., Awaitable[Any]]]] = [
        heartbeat,
        cleanup_privacy,
        generate_digest,
        ingest_document,
        process_message,
        update_lead,
        draft_followups,
        deliver_whatsapp,
    ]
    timezone = UTC
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)

    cron_jobs = [
        cron(schedule_privacy_cleanup, minute=0, run_at_startup=True),
        # Arq schedules in UTC: Monday 03:30 UTC is Monday 09:00 IST.
        cron(schedule_digests, weekday=0, hour=3, minute=30, microsecond=0, run_at_startup=True),
        cron(schedule_followups, minute={0, 15, 30, 45}, run_at_startup=True),
        cron(dispatch_channels, second=set(range(0, 60, 5)), run_at_startup=True),
    ]

    max_tries = 100
    job_timeout = Settings().llm_timeout_s * 10 + 120
