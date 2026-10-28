from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx

from app.channels.delivery import DeliveryService
from app.core.followups import FollowupService
from app.db.models import ChannelDelivery
from app.db.models.channel import DeliveryStatus
from app.repositories.channels import ChannelRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.followups import FollowupRepository
from app.repositories.leads import LeadRepository
from app.repositories.scoped import ScopedRepository
from tests.integration.test_whatsapp_delivery import receive
from tests.integration.test_whatsapp_webhooks import setup_channel
from tests.integration.test_workspace import owner


def registry(status="APPROVED"):
    return {
        "data": [
            {
                "id": "12345",
                "name": "followup",
                "language": "en",
                "status": status,
                "components": [{"type": "BODY", "text": "Would you like help with your enquiry?"}],
            },
            {
                "id": "12346",
                "name": "unpriced",
                "language": "en",
                "status": "APPROVED",
                "components": [{"type": "BODY", "text": "Special price INR 9.99"}],
            },
            {
                "id": "12347",
                "name": "dynamic",
                "language": "en",
                "status": "APPROVED",
                "components": [{"type": "BODY", "text": "Hello {{1}}"}],
            },
        ]
    }


async def test_synced_templates_require_consent_owner_approval_and_current_remote_approval(
    client, sessions
):
    auth, ctx, _, account = await setup_channel(client)
    other, _, _ = await owner(client)
    await receive(client, account)
    app = client._transport.app
    app.state.whatsapp_transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json=registry())
    )
    path = "/api/v1/channels/whatsapp/" + account["id"] + "/templates"
    assert (await client.post(path + "/sync", headers=other)).status_code == 404
    synced = await client.post(path + "/sync", headers=auth)
    assert synced.status_code == 200, synced.text
    values = synced.json()
    assert [entry["name"] for entry in values if entry["usable"]] == ["followup"]
    template = next(entry for entry in values if entry["usable"])
    conversation_id = UUID(
        (await client.get("/api/v1/conversations", headers=auth)).json()[0]["id"]
    )
    now = datetime.now(UTC)
    async with sessions() as session:
        conversation = await ConversationRepository(session, ctx).get(conversation_id)
        conversation.last_customer_msg_at = now - timedelta(days=4)
        conversation.last_business_msg_at = now - timedelta(days=3)
        await LeadRepository(session, ctx).for_conversation(conversation_id, "printing")
        await session.commit()
        await FollowupService(session, ctx, app.state.settings).schedule(now)
        draft = (await FollowupRepository(session, ctx).pending())[0]
        draft_id = str(draft.id)
    action = "/api/v1/followups/" + draft_id + "/action"
    assert (await client.post(action, headers=auth, json={"action": "approve"})).status_code == 409
    assert (
        await client.post(
            action, headers=auth, json={"action": "approve", "template_id": template["id"]}
        )
    ).status_code == 409
    consent = "/api/v1/conversations/" + str(conversation_id) + "/whatsapp-consent"
    assert (
        await client.put(
            consent, headers=other, json={"opted_in": True, "note": "Synthetic consent"}
        )
    ).status_code == 404
    assert (
        await client.put(
            consent, headers=auth, json={"opted_in": True, "note": "Synthetic consent recorded"}
        )
    ).status_code == 200
    assert (
        await client.get("/api/v1/followups/" + draft_id + "/whatsapp-options", headers=other)
    ).status_code == 404
    options = (
        await client.get("/api/v1/followups/" + draft_id + "/whatsapp-options", headers=auth)
    ).json()
    assert len(options["templates"]) == 1 and options["consent"]["opted_in_at"]
    approved = await client.post(
        action, headers=auth, json={"action": "approve", "template_id": template["id"]}
    )
    assert approved.status_code == 200, approved.text
    calls = []

    def respond(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=registry())
        return httpx.Response(200, json={"messages": [{"id": "wamid.template"}]})

    async with sessions() as session:
        delivery = (await ChannelRepository(session, ctx).deliveries())[0]
        await DeliveryService(session, ctx, app.state.settings, httpx.MockTransport(respond)).send(
            delivery.id
        )
        assert delivery.status == DeliveryStatus.SENT
    import json

    assert json.loads(calls[-1].content)["template"] == {
        "name": "followup",
        "language": {"code": "en"},
    }
    assert (
        await client.post(
            action, headers=auth, json={"action": "approve", "template_id": template["id"]}
        )
    ).json()["status"] == "sent"


async def test_uncertain_delivery_needs_explicit_owner_reconciliation(client, sessions):
    auth, ctx, _, account = await setup_channel(client)
    other, _, _ = await owner(client)
    await receive(client, account)
    conversation_id = UUID(
        (await client.get("/api/v1/conversations", headers=auth)).json()[0]["id"]
    )
    from app.db.models import Message

    async with sessions() as session:
        message = await ScopedRepository(session, ctx, Message).create(
            conversation_id=conversation_id, direction="out", sender_type="staff", content="Hello"
        )
        delivery = await ChannelRepository(session, ctx).queue(message)
        delivery.status = DeliveryStatus.UNCERTAIN
        await session.commit()
        delivery_id = str(delivery.id)
    path = "/api/v1/channels/whatsapp/deliveries/" + delivery_id + "/resolve"
    assert (await client.post(path, headers=auth, json={})).status_code == 409
    assert (
        await client.post(path, headers=other, json={"confirmed_not_sent": True})
    ).status_code == 404
    assert (await client.post(path, headers=auth, json={"confirmed_not_sent": True})).json()[
        "status"
    ] == "queued"
    async with sessions() as session:
        delivery = await ScopedRepository(session, ctx, ChannelDelivery).get(UUID(delivery_id))
        delivery.status = DeliveryStatus.UNCERTAIN
        await session.commit()
    assert (
        await client.post(path, headers=auth, json={"provider_message_id": "wamid.confirmed"})
    ).json()["status"] == "sent"
