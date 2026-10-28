import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from redis.asyncio import Redis

from app.channels.delivery import DeliveryService
from app.core.errors import NotFound
from app.db.models import ChannelDelivery, ChannelStatusReceipt, Message
from app.db.models.channel import DeliveryStatus
from app.llm import FakeEmbedder, FakeLLM
from app.llm.offline import agent_response
from app.orchestrator.locks import RedisConversationLock
from app.orchestrator.pipeline import ConversationOrchestrator
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.channels import ChannelRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.scoped import ScopedRepository
from tests.integration.test_whatsapp_webhooks import inbound, setup_channel, signed
from tests.integration.test_workspace import owner


async def receive(client, account, text="Hello"):
    raw, signature = signed(inbound(text, str(uuid4()), phone_id=account["external_id"]))
    response = await client.post("/api/v1/webhooks/whatsapp", content=raw, headers=signature)
    assert response.status_code == 200, response.text


async def test_pipeline_delivery_once_early_status_receipts_and_interactive_staff(
    client, sessions, redis_url
):
    auth, ctx, _, account = await setup_channel(client)
    other_auth, other, _ = await owner(client)
    await receive(client, account)
    conversation_id = UUID(
        (await client.get("/api/v1/conversations", headers=auth)).json()[0]["id"]
    )
    config = client._transport.app.state.settings
    redis = Redis.from_url(redis_url)
    calls = []

    async def respond(request):
        calls.append(json.loads(request.content))
        await asyncio.sleep(0.02)
        return httpx.Response(200, json={"messages": [{"id": "wamid.outgoing." + str(len(calls))}]})

    transport = httpx.MockTransport(respond)
    try:
        async with sessions() as session:
            reply = await ConversationOrchestrator(
                session,
                ctx,
                FakeLLM(DatabaseRunRecorder(sessions), {}, fallback=agent_response),
                FakeEmbedder(),
                RedisConversationLock(redis),
                config,
            ).process(conversation_id)
            assert reply and reply.content.startswith("Hello!")
            delivery = (await ChannelRepository(session, ctx).deliveries())[0]
            delivery_id = delivery.id
            # Simulate a status callback racing ahead of the HTTP send acknowledgement.
            await ChannelRepository(session, ctx).status(
                delivery.account_id, "wamid.outgoing.1", "read"
            )
            await session.commit()

        async def send():
            async with sessions() as session:
                await DeliveryService(session, ctx, config, transport).send(delivery_id)

        await asyncio.gather(send(), send())
        assert len(calls) == 1 and calls[0]["type"] == "text"
        async with sessions() as session:
            delivery = await ScopedRepository(session, ctx, ChannelDelivery).get(delivery_id)
            assert delivery.status == DeliveryStatus.READ
            await ChannelRepository(session, ctx).status(
                delivery.account_id, "wamid.outgoing.1", "sent"
            )
            await ChannelRepository(session, ctx).status(
                delivery.account_id, "wamid.outgoing.1", "failed"
            )
            assert delivery.status == DeliveryStatus.READ
            receipt = (await ScopedRepository(session, ctx, ChannelStatusReceipt).list())[0]
            with pytest.raises(NotFound):
                await ScopedRepository(session, other, ChannelStatusReceipt).get(
                    receipt.id, for_update=True
                )
            assert await ScopedRepository(session, other, ChannelStatusReceipt).list() == []
            await session.commit()
        path = "/api/v1/conversations/" + str(conversation_id)
        assert (
            await client.post(path + "/mode", headers=auth, json={"mode": "human"})
        ).status_code == 204
        body = {
            "content": "How can the team help?",
            "external_id": "interactive",
            "buttons": [{"id": "help", "title": "Ask the team"}],
        }
        assert (
            await client.post(path + "/messages", headers=other_auth, json=body)
        ).status_code == 404
        sent = await client.post(path + "/messages", headers=auth, json=body)
        assert sent.status_code == 201, sent.text
        async with sessions() as session:
            delivery = next(
                row
                for row in await ChannelRepository(session, ctx).deliveries()
                if str(row.message_id) == sent.json()["id"]
            )
            await DeliveryService(session, ctx, config, transport).send(delivery.id)
        assert calls[-1]["type"] == "interactive"
        assert calls[-1]["interactive"]["action"]["buttons"][0]["reply"]["id"] == "help"
    finally:
        await redis.aclose()


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("rate", DeliveryStatus.RETRY),
        ("permanent", DeliveryStatus.FAILED),
        ("timeout", DeliveryStatus.UNCERTAIN),
        ("invalid_price", DeliveryStatus.BLOCKED),
        ("expired", DeliveryStatus.BLOCKED),
    ],
)
async def test_retries_dead_letters_window_and_price_guard(client, sessions, failure, expected):
    auth, ctx, _, account = await setup_channel(client)
    await receive(client, account)
    conversation_id = UUID(
        (await client.get("/api/v1/conversations", headers=auth)).json()[0]["id"]
    )
    calls = []

    def respond(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(
            429 if failure == "rate" else 401,
            json={"error": {"code": 190, "message": "must never be logged"}},
        )

    async with sessions() as session:
        repository = ChannelRepository(session, ctx)
        message = await ScopedRepository(session, ctx, Message).create(
            conversation_id=conversation_id,
            direction="out",
            sender_type="ai",
            content="INR 9.99" if failure == "invalid_price" else "Hello",
        )
        delivery = await repository.queue(message)
        if failure == "expired":
            conversation = await ConversationRepository(session, ctx).get(conversation_id)
            conversation.last_customer_msg_at = datetime.now(UTC) - timedelta(hours=24)
        await session.commit()
        service = DeliveryService(
            session, ctx, client._transport.app.state.settings, httpx.MockTransport(respond)
        )
        await service.send(delivery.id)
        delivery = await ScopedRepository(session, ctx, ChannelDelivery).get(delivery.id)
        assert delivery.status == expected
        assert "must never be logged" not in (delivery.last_error or "")
        if failure in {"invalid_price", "expired"}:
            assert not calls
        if failure == "timeout":
            await service.send(delivery.id)
            assert len(calls) == 1  # ambiguous sends are never automatically retried
        if failure == "rate":
            delivery.attempts = client._transport.app.state.settings.whatsapp_max_attempts - 1
            delivery.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
            await service.send(delivery.id)
            assert delivery.status == DeliveryStatus.FAILED


async def test_media_handoff_is_deterministic_and_staff_cannot_manage_connections(
    client, sessions, redis_url
):
    auth, ctx, user, account = await setup_channel(client)
    raw, signature = signed(
        inbound(
            message_id="wamid.image",
            kind="image",
            details={"image": {"id": "12345", "caption": "Please review"}},
            phone_id=account["external_id"],
        )
    )
    assert (
        await client.post("/api/v1/webhooks/whatsapp", content=raw, headers=signature)
    ).status_code == 200
    conversation_id = UUID(
        (await client.get("/api/v1/conversations", headers=auth)).json()[0]["id"]
    )
    fake = FakeLLM(DatabaseRunRecorder(sessions), {}, fallback=agent_response)
    redis = Redis.from_url(redis_url)
    try:
        async with sessions() as session:
            await ConversationOrchestrator(
                session,
                ctx,
                fake,
                FakeEmbedder(),
                RedisConversationLock(redis),
                client._transport.app.state.settings,
            ).process(conversation_id)
            assert (await ConversationRepository(session, ctx).get(conversation_id)).mode == "human"
            assert [call.agent for call in fake.calls] == ["handoff"]
            from app.db.models import Role
            from app.repositories.identity import UserRepository

            staff = await UserRepository(session, ctx).get(user)
            staff.role = Role.STAFF
            await session.commit()
        assert (await client.get("/api/v1/channels/whatsapp", headers=auth)).status_code == 403
        assert (
            await client.get("/api/v1/channels/whatsapp/setup", headers=auth)
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/channels/whatsapp/deliveries/" + str(uuid4()) + "/resolve",
                headers=auth,
                json={"confirmed_not_sent": True},
            )
        ).status_code == 403
    finally:
        await redis.aclose()


@pytest.mark.parametrize("handoff", [False, True])
async def test_queued_automation_respects_takeover_except_the_handoff_ack(
    client, sessions, handoff
):
    auth, ctx, _, account = await setup_channel(client)
    await receive(client, account)
    conversation_id = UUID(
        (await client.get("/api/v1/conversations", headers=auth)).json()[0]["id"]
    )
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.ack"}]})

    async with sessions() as session:
        message = await ScopedRepository(session, ctx, Message).create(
            conversation_id=conversation_id,
            direction="out",
            sender_type="ai",
            content="The team will review this.",
            attachments=[{"handoff": handoff}],
        )
        delivery = await ChannelRepository(session, ctx).queue(message)
        await session.commit()
    assert (
        await client.post(
            "/api/v1/conversations/" + str(conversation_id) + "/mode",
            headers=auth,
            json={"mode": "human"},
        )
    ).status_code == 204
    async with sessions() as session:
        await DeliveryService(
            session, ctx, client._transport.app.state.settings, httpx.MockTransport(respond)
        ).send(delivery.id)
        delivery = await ScopedRepository(session, ctx, ChannelDelivery).get(delivery.id)
        assert delivery.status == (DeliveryStatus.SENT if handoff else DeliveryStatus.BLOCKED)
        assert len(calls) == int(handoff)
