"""The operator's fallback for a forgotten password when there is no email."""

import httpx
import pytest

from app.core.errors import NotFoundError
from app.db.session import SessionMaker
from app.services.set_password import set_password
from tests.conftest import PASSWORD, register

NEW = "operator-chosen-password-1"


async def test_it_changes_the_password_lifts_a_lockout_and_ends_sessions(
    client: httpx.AsyncClient, sessionmaker: SessionMaker
) -> None:
    email, _ = await register(client)
    await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    old_session = client.cookies.get("munim_refresh")
    assert old_session

    async with sessionmaker() as session:
        await set_password(session, email.upper(), NEW)  # the address is matched in lowercase
        await session.commit()

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": NEW})
    assert login.status_code == 200
    assert (
        await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    ).status_code == 401
    client.cookies.clear()
    client.cookies.set("munim_refresh", old_session, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_it_refuses_a_weak_password_and_an_unknown_account(
    sessionmaker: SessionMaker, client: httpx.AsyncClient
) -> None:
    email, _ = await register(client)
    async with sessionmaker() as session:
        with pytest.raises(ValueError):
            await set_password(session, email, "short")
        with pytest.raises(NotFoundError):
            await set_password(session, "nobody@example.com", NEW)
