"""The limiter's window, who it keys on, and that it can be switched off."""

import uuid

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.ratelimit import SlidingWindowLimiter, rate_limit
from app.core.security import create_access_token


def test_requests_inside_the_limit_pass_and_the_next_is_refused_with_a_wait() -> None:
    limiter = SlidingWindowLimiter()
    assert [limiter.hit("k", 3, 60, now=t) for t in (0, 1, 2)] == [None, None, None]
    wait = limiter.hit("k", 3, 60, now=3)
    assert wait == 58  # the oldest hit leaves the window at t=60


def test_the_window_slides_so_old_requests_stop_counting() -> None:
    limiter = SlidingWindowLimiter()
    for t in (0, 10, 20):
        limiter.hit("k", 3, 60, now=t)
    assert limiter.hit("k", 3, 60, now=30) is not None
    assert limiter.hit("k", 3, 60, now=61) is None  # the t=0 hit has expired


def test_keys_are_independent() -> None:
    limiter = SlidingWindowLimiter()
    limiter.hit("a", 1, 60, now=0)
    assert limiter.hit("a", 1, 60, now=1) is not None
    assert limiter.hit("b", 1, 60, now=1) is None


def test_refused_requests_do_not_extend_the_block() -> None:
    limiter = SlidingWindowLimiter()
    limiter.hit("k", 1, 60, now=0)
    for t in range(1, 50):
        limiter.hit("k", 1, 60, now=t)  # hammering while blocked
    assert limiter.hit("k", 1, 60, now=61) is None


def test_memory_is_bounded_when_many_distinct_keys_arrive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.ratelimit._MAX_KEYS", 100)
    limiter = SlidingWindowLimiter()
    for i in range(500):
        limiter.hit(f"ip-{i}", 5, 10, now=float(i))  # each key expires 10 s after its one hit
    assert len(limiter._hits) <= 101  # noqa: SLF001


def make_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.state.limiter = SlidingWindowLimiter()

    @app.get("/by-ip", dependencies=[Depends(rate_limit("ip", 2, 60))])
    async def by_ip() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/by-tenant", dependencies=[Depends(rate_limit("tenant", 2, 60, by="tenant"))])
    async def by_tenant() -> dict[str, bool]:
        return {"ok": True}

    @app.exception_handler(DomainError)
    async def handler(_, exc: DomainError):  # type: ignore[no-untyped-def]
        from fastapi.responses import JSONResponse

        retry = getattr(exc, "retry_after", None)
        return JSONResponse(
            {"error": exc.code}, status_code=exc.status_code, headers={"Retry-After": str(retry)}
        )

    return app


def client_for(settings: Settings) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=make_app(settings), client=("203.0.113.7", 1234))
    return httpx.AsyncClient(transport=transport, base_url="http://t")


SETTINGS = Settings(_env_file=None, app_env="test", secret_key="s" * 40)


async def test_the_third_request_gets_429_with_retry_after() -> None:
    async with client_for(SETTINGS) as client:
        assert [(await client.get("/by-ip")).status_code for _ in range(2)] == [200, 200]
        refused = await client.get("/by-ip")
    assert refused.status_code == 429 and int(refused.headers["Retry-After"]) >= 1
    assert refused.json() == {"error": "rate_limited"}


async def test_each_business_has_its_own_allowance() -> None:
    user = uuid.uuid4()
    first = {"Authorization": "Bearer " + create_access_token(SETTINGS, user, uuid.uuid4())}
    second = {"Authorization": "Bearer " + create_access_token(SETTINGS, user, uuid.uuid4())}
    async with client_for(SETTINGS) as client:
        for _ in range(2):
            assert (await client.get("/by-tenant", headers=first)).status_code == 200
        assert (await client.get("/by-tenant", headers=first)).status_code == 429
        assert (await client.get("/by-tenant", headers=second)).status_code == 200  # untouched


async def test_a_bad_token_is_limited_by_address_not_waved_through() -> None:
    bad = {"Authorization": "Bearer not-a-token"}
    async with client_for(SETTINGS) as client:
        codes = [(await client.get("/by-tenant", headers=bad)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]  # the route has no auth here; the limiter still counted


async def test_the_proxy_header_is_used_only_when_it_is_configured() -> None:
    spoof = {"CF-Connecting-IP": "198.51.100.9"}
    async with client_for(SETTINGS) as client:  # not configured: the header is ignored
        statuses = [
            (await client.get("/by-ip", headers={"CF-Connecting-IP": f"1.1.1.{i}"})).status_code
            for i in range(3)
        ]
    assert statuses == [200, 200, 429]  # spoofing a new address each time does not help

    behind_proxy = SETTINGS.model_copy(update={"trusted_proxy_header": "CF-Connecting-IP"})
    async with client_for(behind_proxy) as client:
        assert [(await client.get("/by-ip", headers=spoof)).status_code for _ in range(2)] == [
            200,
            200,
        ]
        assert (await client.get("/by-ip", headers=spoof)).status_code == 429
        other = {"CF-Connecting-IP": "198.51.100.10"}
        assert (await client.get("/by-ip", headers=other)).status_code == 200  # a different user


async def test_it_can_be_switched_off() -> None:
    off = SETTINGS.model_copy(update={"rate_limit_enabled": False})
    async with client_for(off) as client:
        assert {(await client.get("/by-ip")).status_code for _ in range(10)} == {200}
