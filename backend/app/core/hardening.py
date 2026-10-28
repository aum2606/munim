import asyncio
from collections.abc import Awaitable
from hashlib import sha256
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import DomainError


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def check(self, key: str, limit: int) -> None:
        script = (
            "local n=redis.call('INCR',KEYS[1]); "
            "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n"
        )
        try:
            count = await cast(
                Awaitable[int],
                self.redis.eval(script, 1, "api:rate:" + sha256(key.encode()).hexdigest()),
            )
        except (RedisError, OSError) as error:
            raise DomainError("Request limiting is unavailable; please retry", 503) from error
        if count > limit:
            raise DomainError("Too many requests; retry after one minute", 429)


class RequestSafetyMiddleware:
    """Bound streaming bodies before validation/multipart parsing; never log or echo body data."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app, self.settings = app, settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def safe_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                for key, value in [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                ]:
                    if key not in existing:
                        headers.append((key, value))
                message = {**message, "headers": headers}
            await send(message)

        if scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, safe_send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        is_json = headers.get(b"content-type", b"").split(b";")[0].strip().endswith(b"json")
        limit = self.settings.max_json_bytes if is_json else self.settings.max_request_bytes
        if scope["path"].startswith("/api/v1/webhooks/"):
            limit = min(self.settings.max_request_bytes, 1024 * 1024)
        try:
            declared = int(headers.get(b"content-length", b"0"))
            if declared < 0:
                raise ValueError
        except ValueError:
            await JSONResponse({"detail": "Invalid request length"}, 400)(scope, receive, safe_send)
            return
        if declared > limit:
            await JSONResponse({"detail": "Request body too large"}, 413)(scope, receive, safe_send)
            return
        body = bytearray()
        try:
            async with asyncio.timeout(self.settings.request_body_timeout_s):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > limit:
                        await JSONResponse({"detail": "Request body too large"}, 413)(
                            scope, receive, safe_send
                        )
                        return
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await JSONResponse({"detail": "Request body timed out"}, 408)(scope, receive, safe_send)
            return
        delivered = False

        async def buffered_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, safe_send)
