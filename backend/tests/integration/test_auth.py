from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound, Unauthorized
from app.core.security import token_hash
from app.core.tenant import TenantContext
from app.db.models import Role
from app.repositories.identity import TenantRepository, UserRepository
from app.repositories.sessions import SessionRepository


async def register(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Demo Printing",
            "business_type": "printing",
            "name": "Demo Owner",
            "email": f"owner-{uuid4()}@example.com",
            "password": "test-password-long",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth(tokens: dict[str, str]) -> dict[str, str]:
    return {"Authorization": "Bearer " + tokens["access_token"]}


async def test_register_login_validation_and_refresh(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/me")).status_code == 401
    invalid = await client.post("/api/v1/auth/register", json={"password": "private"})
    assert invalid.status_code == 422
    assert "private" not in invalid.text
    a = await register(client)
    profile = await client.get("/api/v1/me", headers=auth(a))
    assert profile.status_code == 200
    owner = profile.json()
    assert owner["role"] == "owner"
    assert "password_hash" not in owner
    login = await client.post(
        "/api/v1/auth/login", json={"email": owner["email"], "password": "test-password-long"}
    )
    assert login.status_code == 200
    bad = await client.post(
        "/api/v1/auth/login", json={"email": owner["email"], "password": "wrong"}
    )
    assert bad.status_code == 401
    duplicate = await client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Other",
            "business_type": "printing",
            "name": "Other Owner",
            "email": owner["email"],
            "password": "test-password-long",
        },
    )
    assert duplicate.status_code == 409
    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != a["refresh_token"]
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert replay.status_code == 401
    assert (
        await client.get("/api/v1/me", headers={"Authorization": "Bearer " + a["refresh_token"]})
    ).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": a["access_token"]})
    ).status_code == 401
    fresh = refreshed.json()
    assert (
        await client.post("/api/v1/auth/logout", json={"refresh_token": fresh["refresh_token"]})
    ).status_code == 204
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": fresh["refresh_token"]})
    ).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid"})
    ).status_code == 401


async def test_users_cross_tenant_read_write_and_settings_isolation(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    a, b = await register(client), await register(client)
    owner_a = (await client.get("/api/v1/me", headers=auth(a))).json()
    owner_b = (await client.get("/api/v1/me", headers=auth(b))).json()
    assert owner_a["tenant_id"] != owner_b["tenant_id"]
    listing = await client.get("/api/v1/users", headers=auth(a))
    assert listing.status_code == 200
    assert [u["id"] for u in listing.json()] == [owner_a["id"]]
    route = "/api/v1/users/" + owner_b["id"]
    assert (await client.get(route, headers=auth(a))).status_code == 404
    assert (
        await client.patch(route, headers=auth(a), json={"name": "Intruder"})
    ).status_code == 404
    assert (await client.get(route)).status_code == 401
    assert (await client.patch(route, headers=auth(b), json={"name": ""})).status_code == 422
    updated = await client.patch(route, headers=auth(b), json={"name": "Renamed Owner"})
    assert updated.status_code == 200 and updated.json()["name"] == "Renamed Owner"
    ctx_a = TenantContext(UUID(owner_a["tenant_id"]))
    ctx_b = TenantContext(UUID(owner_b["tenant_id"]))
    async with sessions() as session:
        with pytest.raises(NotFound):
            await UserRepository(session, ctx_a).rename(UUID(owner_b["id"]), "Intruder")
        assert (await TenantRepository(session, ctx_a).get()).id == ctx_a.tenant_id
        settings_a = await TenantRepository(session, ctx_a).settings()
        settings_b = await TenantRepository(session, ctx_b).settings()
        assert settings_a.tenant_id != settings_b.tenant_id
        settings_a.tone = "formal"
        await session.commit()
    async with sessions() as session:
        assert (await TenantRepository(session, ctx_b).settings()).tone == "friendly"
        assert await SessionRepository(session, ctx_a).get(token_hash(b["refresh_token"])) is None
        await SessionRepository(session, ctx_a).revoke(token_hash(b["refresh_token"]))
        await session.commit()
        with pytest.raises(Unauthorized):
            from datetime import UTC, datetime

            await SessionRepository(session, ctx_a).consume(
                token_hash(b["refresh_token"]), datetime.now(UTC)
            )


async def test_staff_role_and_inactive_account(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    tokens = await register(client)
    owner = (await client.get("/api/v1/me", headers=auth(tokens))).json()
    async with sessions() as session:
        user = await UserRepository(session, TenantContext(UUID(owner["tenant_id"]))).get(
            UUID(owner["id"])
        )
        user.role = Role.STAFF
        await session.commit()
    assert (await client.get("/api/v1/users", headers=auth(tokens))).status_code == 403
    assert (await client.get("/api/v1/me", headers=auth(tokens))).json()["role"] == "staff"
    async with sessions() as session:
        user = await UserRepository(session, TenantContext(UUID(owner["tenant_id"]))).get(
            UUID(owner["id"])
        )
        user.is_active = False
        await session.commit()
    assert (await client.get("/api/v1/me", headers=auth(tokens))).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401


async def test_atomic_refresh_cannot_be_consumed_twice(client: httpx.AsyncClient) -> None:
    import asyncio

    tokens = await register(client)
    results = await asyncio.gather(
        *[
            client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
            for _ in range(2)
        ]
    )
    assert sorted(response.status_code for response in results) == [200, 401]
