import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import yaml
from cryptography.fernet import Fernet
from pydantic import SecretStr
from redis.asyncio import Redis

from app.channels.delivery import DeliveryService
from app.llm import FakeEmbedder, FakeLLM
from app.llm.offline import agent_response
from app.orchestrator.locks import RedisConversationLock
from app.orchestrator.pipeline import ConversationOrchestrator
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.channels import ChannelRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.identity import TenantRepository
from tests.integration.test_quote_approval import setup_quote
from tests.integration.test_whatsapp_webhooks import inbound, signed
from tests.integration.test_workspace import FakeQueue


@pytest.mark.parametrize("expired", [False, True])
async def test_whatsapp_signed_enquiry_requirements_owner_approval_and_pdf_document(
    client, sessions, redis_url, tmp_path, expired
):
    auth, ctx, _, _, _ = await setup_quote(client, sessions, tmp_path)
    app = client._transport.app
    app.state.jobs = FakeQueue()
    config = app.state.settings
    config.credentials_encryption_key = SecretStr(Fernet.generate_key().decode())
    config.whatsapp_app_secret = SecretStr("synthetic-app-secret")
    config.whatsapp_api_version = "v23.0"
    phone_id = str(uuid4().int)[:15]
    sent = []
    uploads = []

    def respond(request):
        if request.url.path.endswith("/subscribed_apps"):
            return httpx.Response(200, json={"success": True})
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": phone_id}]})
        if request.url.path.endswith("/media"):
            uploads.append(request.content)
            assert b"%PDF-" in request.content and b"application/pdf" in request.content
            return httpx.Response(200, json={"id": "1234567"})
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.sent." + str(len(sent))}]})

    transport = httpx.MockTransport(respond)
    app.state.whatsapp_transport = transport
    connected = await client.post(
        "/api/v1/channels/whatsapp",
        headers=auth,
        json={
            "phone_number_id": phone_id,
            "business_account_id": "123456789",
            "access_token": "synthetic-provider-token",
        },
    )
    assert connected.status_code == 201, connected.text
    case = yaml.safe_load(
        (Path(__file__).parent / "phase4_conversations.yaml").read_text(encoding="utf-8")
    )
    redis = Redis.from_url(redis_url)
    conversation_id = None
    original_policy = None
    try:
        async with sessions() as session:
            settings = await TenantRepository(session, ctx).settings()
            original_policy = settings.auto_send_quotes
            settings.auto_send_quotes = False
            await session.commit()
        for index, text in enumerate(case["turns"]):
            raw, signature = signed(inbound(text, "wamid.turn." + str(index), phone_id=phone_id))
            assert (
                await client.post("/api/v1/webhooks/whatsapp", content=raw, headers=signature)
            ).status_code == 200
            conversations = (
                await client.get("/api/v1/conversations?channel=whatsapp", headers=auth)
            ).json()
            conversation_id = UUID(
                next(entry["id"] for entry in conversations if entry["channel"] == "whatsapp")
            )
            async with sessions() as session:
                fake = FakeLLM(DatabaseRunRecorder(sessions), {}, fallback=agent_response)
                await ConversationOrchestrator(
                    session, ctx, fake, FakeEmbedder(), RedisConversationLock(redis), config
                ).process(conversation_id)
                for delivery in reversed(await ChannelRepository(session, ctx).deliveries()):
                    await DeliveryService(session, ctx, config, transport).send(delivery.id)
            # Provider duplicate deliveries neither refresh the window nor create another turn.
            assert (
                await client.post("/api/v1/webhooks/whatsapp", content=raw, headers=signature)
            ).status_code == 200
        quote = next(
            quote
            for quote in (await client.get("/api/v1/quotes", headers=auth)).json()
            if quote["conversation_id"] == str(conversation_id)
        )
        assert quote["totals"]["total_paise"] == case["expected_total_paise"]
        path = "/api/v1/quotes/" + quote["id"] + "/approve"
        assert (
            await client.post(path, headers=auth, json={"expected_version": quote["version"]})
        ).status_code == 200
        if expired:
            from app.repositories.quotes import QuoteRepository

            async with sessions() as session:
                stale_quote = await QuoteRepository(session, ctx).get(UUID(quote["id"]))
                stale_quote.valid_until = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()
        async with sessions() as session:
            for delivery in reversed(await ChannelRepository(session, ctx).deliveries()):
                await DeliveryService(session, ctx, config, transport).send(delivery.id)
            assert len(await ConversationRepository(session, ctx).messages(conversation_id)) == 5
        if expired:
            assert len(uploads) == 0 and len(sent) == 2
            return
        assert len(uploads) == 1 and len(sent) == 3
        assert sent[-1]["type"] == "document"
        assert sent[-1]["document"]["id"] == "1234567"
        assert "₹3,245.00" in sent[-1]["document"]["caption"]
        assert (
            await client.post(path, headers=auth, json={"expected_version": quote["version"]})
        ).status_code == 200
        async with sessions() as session:
            for delivery in await ChannelRepository(session, ctx).deliveries():
                await DeliveryService(session, ctx, config, transport).send(delivery.id)
        assert len(sent) == 3
    finally:
        if original_policy is not None:
            async with sessions() as session:
                settings = await TenantRepository(session, ctx).settings()
                settings.auto_send_quotes = original_policy
                await session.commit()
        await redis.aclose()
