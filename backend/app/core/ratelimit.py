"""Rate limiting without Redis: a sliding window kept in this process.

shortcut: the counters live in one API process, so with several replicas each enforces its own
limit (the real ceiling is limit x replicas). Upgrade to a Postgres counter if that matters.
"""

import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Literal, NamedTuple

from fastapi import Request

from app.core.config import Settings
from app.core.errors import DomainError, RateLimitedError
from app.core.security import decode_access_token

_MAX_KEYS = 50_000  # a flood of distinct keys must not grow memory without bound


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, limit: int, window_s: float, now: float | None = None) -> int | None:
        """Count a request. Returns None if allowed, else the seconds until one would be."""
        now = time.monotonic() if now is None else now
        if len(self._hits) > _MAX_KEYS:
            self._purge(now, window_s)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= window_s:
            hits.popleft()
        if len(hits) >= limit:
            return max(1, int(window_s - (now - hits[0])) + 1)
        hits.append(now)
        return None

    def _purge(self, now: float, window_s: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= window_s]:
            del self._hits[key]


def client_ip(request: Request, settings: Settings) -> str:
    """The caller's address. Behind a proxy (Cloudflare Tunnel) the socket address is the proxy's,
    so a trusted header may be named in TRUSTED_PROXY_HEADER; never trust one you do not control."""
    if settings.trusted_proxy_header:
        value = request.headers.get(settings.trusted_proxy_header, "").split(",")[0].strip()
        if value:
            return value
    return request.client.host if request.client else "unknown"


def _tenant_key(request: Request, settings: Settings) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        return str(decode_access_token(settings, header[7:]).tenant_id)
    except DomainError:
        return None  # a bad token is refused by authentication; limit it by address meanwhile


class Limit(NamedTuple):
    requests: int
    window_s: int


# Every limit in one place. "api" and "playground" count per business; the rest per address.
LIMITS: dict[str, Limit] = {
    "register": Limit(5, 3600),
    "login": Limit(10, 60),
    "refresh": Limit(30, 60),
    "forgot_password": Limit(5, 3600),  # each one can send an email
    "reset_password": Limit(10, 3600),
    "playground": Limit(30, 60),  # per business
    "api": Limit(300, 60),  # per business
    "webhook": Limit(1200, 60),  # generous: Meta sends in bursts
}


def limited(
    name: str, *, by: Literal["ip", "tenant"] = "ip"
) -> Callable[[Request], Awaitable[None]]:
    """The named limit from `LIMITS` as a FastAPI dependency."""
    return rate_limit(name, *LIMITS[name], by=by)


def rate_limit(
    name: str, limit: int, window_s: int, *, by: Literal["ip", "tenant"] = "ip"
) -> Callable[[Request], Awaitable[None]]:
    """A FastAPI dependency: `dependencies=[Depends(rate_limit("login", 10, 60))]`."""

    async def check(request: Request) -> None:
        settings: Settings = request.app.state.settings
        if not settings.rate_limit_enabled:
            return
        who = (_tenant_key(request, settings) if by == "tenant" else None) or client_ip(
            request, settings
        )
        wait = request.app.state.limiter.hit(f"{name}:{who}", limit, window_s)
        if wait is not None:
            raise RateLimitedError(wait)

    return check
