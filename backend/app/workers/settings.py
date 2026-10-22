from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import Settings


async def heartbeat(ctx: dict[str, Any]) -> str:
    """A minimal diagnostic task keeps the foundation worker runnable."""
    return "ok"


class WorkerSettings:
    functions: ClassVar[list[Callable[..., Awaitable[str]]]] = [heartbeat]
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)
