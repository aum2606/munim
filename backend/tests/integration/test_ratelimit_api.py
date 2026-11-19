"""The limits on the real routes: login, register, refresh, the webhook."""

import hashlib
import hmac
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from app.core.config import Settings
from app.db.session import SessionMaker
from app.llm.fake import FakeLLM
from app.main import create_app
from tests.conftest import PASSWORD, register, unique_email


@pytest.fixture
async def limited(
    settings: Settings, sessionmaker: SessionMaker, llm: FakeLLM
) -> AsyncIterator[httpx.AsyncClient]:
    enabled = settings.model_copy(
        update={"rate_limit_enabled": True, "whatsapp_app_secret": "s3cret"}
    )
    app = create_app(enabled)
    app.state.sessionmaker = sessionmaker
    app.state.llm = llm
    transport = httpx.ASGITransport(app=app, client=("203.0.113.50", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_login_is_limited_per_address_with_a_retry_hint(limited: httpx.AsyncClient) -> None:
    body = {"email": unique_email(), "password": "wrong password"}
    codes = [(await limited.post("/api/v1/auth/login", json=body)).status_code for _ in range(10)]
    assert set(codes) == {401}  # ten tries get an honest answer
    refused = await limited.post("/api/v1/auth/login", json=body)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "rate_limited"
    assert int(refused.headers["Retry-After"]) >= 1


async def test_registration_is_limited_to_five_an_hour_per_address(
    limited: httpx.AsyncClient,
) -> None:
    for _ in range(5):
        await register(limited)
    response = await limited.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Sixth Press",
            "business_type": "printing",
            "name": "Owner",
            "email": unique_email(),
            "password": PASSWORD,
        },
    )
    assert response.status_code == 429


async def test_a_prober_sending_bad_webhook_signatures_is_shut_out(
    limited: httpx.AsyncClient,
) -> None:
    body = json.dumps({"entry": []}).encode()
    bad = {"X-Hub-Signature-256": "sha256=00"}
    codes = [
        (await limited.post("/webhooks/whatsapp", content=body, headers=bad)).status_code
        for _ in range(20)
    ]
    assert set(codes) == {403}
    assert (await limited.post("/webhooks/whatsapp", content=body, headers=bad)).status_code == 429

    # A correctly signed request from the same address is not counted as probing.
    good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    ok = await limited.post(
        "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": good}
    )
    assert ok.status_code == 200
