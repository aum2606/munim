from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import LockError

from app.core.errors import DomainError


class ConversationLock(Protocol):
    def hold(self, tenant_id: UUID, conversation_id: UUID) -> AbstractAsyncContextManager[None]: ...


class RedisConversationLock:
    def __init__(self, redis: Redis, timeout: int = 300) -> None:
        self.redis, self.timeout = redis, timeout

    @asynccontextmanager
    async def hold(self, tenant_id: UUID, conversation_id: UUID) -> AsyncIterator[None]:
        try:
            async with self.redis.lock(
                f"conversation:{tenant_id}:{conversation_id}",
                timeout=self.timeout,
                blocking_timeout=1,
            ):
                yield
        except LockError as error:
            raise DomainError("Conversation is busy", 409) from error
