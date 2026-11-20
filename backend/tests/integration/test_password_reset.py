"""Forgot password: a one-time emailed link, the same answer for every address, no secrets kept."""

import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update

from app.core.config import Settings
from app.db.models import Job, PasswordResetToken, User
from app.db.session import SessionMaker
from app.jobs.handlers import build_handlers
from app.jobs.worker import process_batch
from app.llm.embedder import FakeEmbedder
from app.llm.fake import FakeLLM
from app.services.mailer import FakeMailer
from app.services.password_reset import request_reset
from tests.conftest import PASSWORD, register, unique_email

NEW_PASSWORD = "a-brand-new-password-1"
ASKED = "If that address has an account, a reset link is on its way."


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "smtp_host": "smtp.test",
            "smtp_from": "Munim <noreply@munim.test>",
            "public_url": "https://munim.test/",
        }
    )


async def ask(client: httpx.AsyncClient, email: str) -> httpx.Response:
    return await client.post("/api/v1/auth/forgot-password", json={"email": email})


async def send_queued(sm: SessionMaker, settings: Settings) -> FakeMailer:
    mailer = FakeMailer()
    handlers = build_handlers(FakeEmbedder(), settings, FakeLLM([]), mailer=mailer)
    while await process_batch(sm, handlers, limit=100):  # the database is shared: drain it all
        pass
    return mailer


def recipients(mailer: FakeMailer, *among: str) -> list[str]:
    """Who was mailed, limited to this test's own addresses (other tests share the database)."""
    return [to for to, _, _ in mailer.sent if to in among]


def token_in(mailer: FakeMailer, email: str) -> str:
    (_, _, body) = [m for m in mailer.sent if m[0] == email][-1]
    found = re.search(r"https://munim\.test/reset-password\?token=(\S+)", body)
    assert found, "the link starts with PUBLIC_URL, without a doubled slash"
    return found.group(1)


async def reset(client: httpx.AsyncClient, token: str, password: str = NEW_PASSWORD) -> int:
    response = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": password}
    )
    return response.status_code


async def sign_in(client: httpx.AsyncClient, email: str, password: str) -> int:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.status_code


async def test_the_link_sets_a_new_password_once_and_ends_every_session(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    email, _ = await register(client)
    await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    old_session = client.cookies.get("munim_refresh")
    assert old_session

    asked = await ask(client, email)
    assert asked.status_code == 202 and asked.json() == {"detail": ASKED}
    mailer = await send_queued(sessionmaker, settings)
    assert recipients(mailer, email) == [email]
    token = token_in(mailer, email)

    assert await reset(client, token, "short") == 422  # the usual password rules apply
    assert await reset(client, token) == 204
    assert await sign_in(client, email, PASSWORD) == 401
    assert await sign_in(client, email, NEW_PASSWORD) == 200
    client.cookies.clear()
    client.cookies.set("munim_refresh", old_session, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401  # signed out everywhere
    assert await reset(client, token, "another-password-9") == 409  # a link works only once


async def test_an_unknown_address_gets_the_same_answer_and_no_email(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    known, _ = await register(client)
    unknown = unique_email()
    answers = [await ask(client, known), await ask(client, unknown)]
    assert [(a.status_code, a.json()) for a in answers] == [(202, {"detail": ASKED})] * 2
    mailer = await send_queued(sessionmaker, settings)
    assert recipients(mailer, known, unknown) == [known]  # only the real account was mailed


async def test_a_deactivated_account_gets_no_email(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    email, _ = await register(client)
    async with sessionmaker() as session:
        await session.execute(update(User).where(User.email == email).values(is_active=False))
        await session.commit()
    await ask(client, email)
    assert recipients(await send_queued(sessionmaker, settings), email) == []


async def test_only_the_hash_is_stored_and_a_new_link_replaces_the_old_one(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    email, _ = await register(client)
    await ask(client, email)
    first = token_in(await send_queued(sessionmaker, settings), email)
    await ask(client, email)
    second = token_in(await send_queued(sessionmaker, settings), email)

    async with sessionmaker() as session:
        stored = list(
            await session.scalars(
                select(PasswordResetToken.token_hash)
                .join(User, User.id == PasswordResetToken.user_id)
                .where(User.email == email)
            )
        )
    assert len(stored) == 2 and first not in stored and second not in stored
    assert await reset(client, first) == 409
    assert await reset(client, second) == 204


async def test_an_expired_or_made_up_link_is_refused_with_one_message(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    email, _ = await register(client)
    await ask(client, email)
    token = token_in(await send_queued(sessionmaker, settings), email)
    async with sessionmaker() as session:
        await session.execute(
            update(PasswordResetToken).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()

    expired = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    made_up = await client.post(
        "/api/v1/auth/reset-password", json={"token": "x" * 40, "password": NEW_PASSWORD}
    )
    assert expired.status_code == made_up.status_code == 409
    assert expired.json() == made_up.json()
    assert await sign_in(client, email, PASSWORD) == 200  # nothing changed


async def test_resetting_lifts_a_lockout(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    email, _ = await register(client)
    for _ in range(5):
        await sign_in(client, email, "wrong-password-1")
    assert await sign_in(client, email, PASSWORD) == 401  # locked out for 15 minutes
    await ask(client, email)
    assert await reset(client, token_in(await send_queued(sessionmaker, settings), email)) == 204
    assert await sign_in(client, email, NEW_PASSWORD) == 200


async def test_without_smtp_nothing_is_queued_but_the_answer_is_the_same(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    email, _ = await register(client)
    async with sessionmaker() as session:
        await request_reset(session, settings.model_copy(update={"smtp_host": ""}), email)
        await session.commit()
        queued = await session.scalar(
            select(func.count())
            .select_from(Job)
            .join(User, User.tenant_id == Job.tenant_id)
            .where(Job.kind == "send_password_reset", User.email == email)
        )
    assert queued == 0


async def test_the_requests_are_validated(client: httpx.AsyncClient) -> None:
    forgot, reset_url = "/api/v1/auth/forgot-password", "/api/v1/auth/reset-password"
    assert (await client.post(forgot, json={})).status_code == 422
    assert (await client.post(forgot, json={"email": "no"})).status_code == 422
    extra = await client.post(forgot, json={"email": unique_email(), "admin": True})
    assert extra.status_code == 422
    blank = await client.post(reset_url, json={"token": "", "password": NEW_PASSWORD})
    assert blank.status_code == 422
