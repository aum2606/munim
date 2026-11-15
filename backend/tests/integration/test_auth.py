import uuid

import httpx
from sqlalchemy import select

from app.core.config import Settings
from app.core.security import create_access_token
from app.db.models import RefreshToken, User
from app.db.session import SessionMaker
from app.main import create_app
from tests.conftest import PASSWORD, bearer, register, unique_email


def _registration(**overrides: str) -> dict[str, str]:
    body = {
        "business_name": "B",
        "business_type": "printing",
        "name": "O",
        "email": unique_email(),
        "password": PASSWORD,
    }
    return {**body, **overrides}


async def test_register_then_me(client: httpx.AsyncClient) -> None:
    email, token = await register(client)
    me = await client.get("/api/v1/me", headers=bearer(token))
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["email"] == email and body["user"]["role"] == "owner"
    assert body["tenant"]["name"] == "Test Press" and body["tenant"]["timezone"] == "Asia/Kolkata"
    assert "password" not in me.text


async def test_register_sets_a_hardened_refresh_cookie(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json=_registration())
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1/auth" in cookie
    assert "refresh_token" not in response.json()  # never in the body, so JS can't read it


async def test_register_rejects_duplicate_email_case_insensitively(
    client: httpx.AsyncClient,
) -> None:
    email, _ = await register(client)
    again = await client.post("/api/v1/auth/register", json=_registration(email=email.upper()))
    assert again.status_code == 409


async def test_register_validation_never_echoes_the_password(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json=_registration(password="short-pw"))
    assert response.status_code == 422
    assert "short-pw" not in response.text


async def test_unknown_fields_are_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json=_registration(role="owner"))
    assert response.status_code == 422


async def test_registration_can_be_disabled(settings: Settings, sessionmaker: SessionMaker) -> None:
    app = create_app(settings.model_copy(update={"allow_registration": False}))
    app.state.sessionmaker = sessionmaker
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        response = await c.post("/api/v1/auth/register", json=_registration())
    assert response.status_code == 403


async def test_login_success_and_generic_failures(client: httpx.AsyncClient) -> None:
    email, _ = await register(client)
    ok = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["token_type"] == "bearer"

    wrong = await client.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": unique_email(), "password": "nope"}
    )
    # Same status and body: the response does not reveal whether the email exists.
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_account_locks_after_repeated_failures(
    client: httpx.AsyncClient, sessionmaker: SessionMaker
) -> None:
    email, _ = await register(client)
    for _ in range(5):
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
        assert r.status_code == 401
    # The counter was persisted, so even the right password is now refused.
    locked = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert locked.status_code == 401
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None and user.locked_until is not None


async def test_refresh_rotates_and_replay_revokes_every_session(
    client: httpx.AsyncClient, sessionmaker: SessionMaker
) -> None:
    email, _ = await register(client)
    first_cookie = client.cookies["munim_refresh"]

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    second_cookie = client.cookies["munim_refresh"]
    assert second_cookie != first_cookie

    # Replaying the old (rotated-out) token looks like theft: it fails and kills the new one too.
    client.cookies.clear()
    client.cookies.set("munim_refresh", first_cookie, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    client.cookies.clear()
    client.cookies.set("munim_refresh", second_cookie, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        live = await session.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            )
        )
        assert list(live) == []


async def test_refresh_requires_a_valid_cookie(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    client.cookies.set("munim_refresh", "garbage", path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_revokes_the_refresh_token(client: httpx.AsyncClient) -> None:
    await register(client)
    stolen = client.cookies["munim_refresh"]
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    client.cookies.set("munim_refresh", stolen, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_protected_routes_need_a_valid_unexpired_token(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    assert (await client.get("/api/v1/me")).status_code == 401
    assert (await client.get("/api/v1/me", headers=bearer("garbage"))).status_code == 401
    _, token = await register(client)
    me = (await client.get("/api/v1/me", headers=bearer(token))).json()
    expired = Settings(app_env="test", secret_key=settings.secret_key, access_token_minutes=-1)
    old = create_access_token(expired, uuid.UUID(me["user"]["id"]), uuid.UUID(me["tenant"]["id"]))
    assert (await client.get("/api/v1/me", headers=bearer(old))).status_code == 401
