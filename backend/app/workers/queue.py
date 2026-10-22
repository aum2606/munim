from typing import Protocol
from uuid import UUID

from arq.connections import RedisSettings, create_pool
from redis.exceptions import RedisError

from app.core.errors import DomainError


class JobQueue(Protocol):
    async def enqueue(self, task: str, tenant_id: UUID, resource_id: UUID) -> None: ...


class ArqJobQueue:
    def __init__(self, redis_url: str, debounce_seconds: float = 2.5) -> None:
        self.redis_url = redis_url
        self.debounce_seconds = debounce_seconds

    async def enqueue(self, task: str, tenant_id: UUID, resource_id: UUID) -> None:
        try:
            pool = await create_pool(RedisSettings.from_dsn(self.redis_url), retry=0)
            try:
                await pool.enqueue_job(
                    task,
                    str(tenant_id),
                    str(resource_id),
                    _job_id=f"{task}:{tenant_id}:{resource_id}",
                    _defer_by=self.debounce_seconds if task == "process_message" else None,
                )
            finally:
                await pool.aclose()
        except (RedisError, OSError) as error:
            raise DomainError(
                "Background queue is unavailable; retry this pending job", 503
            ) from error
