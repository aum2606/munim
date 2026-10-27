import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.repositories.channels import ChannelRepository
from app.repositories.conversations import ConversationRepository
from tests.integration.test_workspace import owner


def signed(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return raw, {
        "X-Hub-Signature-256": "sha256="
        + hmac.new(b"synthetic-app-secret", raw, hashlib.sha256).hexdigest()
    }


def inbound(text="Hello", message_id="wamid.synthetic", kind="text", details=None):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "987654321"},
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "919000000001",
                                    "timestamp": str(int(datetime.now(UTC).timestamp())),
                                    "type": kind,
                                    **(details or {"text": {"body": text}}),
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


async def setup_channel(client):
    auth, ctx, user = await owner(client)
    app = client._transport.app
    app.state.settings.credentials_encryption_key = SecretStr(Fernet.generate_key().decode())
    app.state.settings.whatsapp_api_version = "v23.0"
    app.state.settings.whatsapp_app_secret = SecretStr("synthetic-app-secret")
    app.state.settings.whatsapp_verify_token = SecretStr("synthetic-verify-token")
    app.state.whatsapp_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "987654321"}]})
    )

    class Queue:
        jobs = []

        async def enqueue(self, *args):
            self.jobs.append(args)

    app.state.jobs = Queue()
    response = await client.post(
        "/api/v1/channels/whatsapp",
        headers=auth,
        json={
            "phone_number_id": "987654321",
            "business_account_id": "123456789",
            "access_token": "synthetic-provider-token",
        },
    )
    assert response.status_code == 201, response.text
    return auth, ctx, user, response.json()


async def test_verified_connection_signed_inbound_dedup_and_isolation(client, sessions):
    a, ctx, _, account = await setup_channel(client)
    b, other, _ = await owner(client)
    app = client._transport.app
    assert (await client.get("/api/v1/channels/whatsapp")).status_code == 401
    assert "credential" not in json.dumps(account) and "token" not in json.dumps(account)
    assert (await client.get("/api/v1/channels/whatsapp", headers=b)).json() == []
    assert (
        await client.patch(
            "/api/v1/channels/whatsapp/" + account["id"], headers=b, json={"status": "disabled"}
        )
    ).status_code == 404
    assert (await client.post("/api/v1/channels/whatsapp", headers=a, json={})).status_code == 422
    verify = (
        "/api/v1/webhooks/whatsapp?hub.mode=subscribe"
        "&hub.verify_token=synthetic-verify-token&hub.challenge=123"
    )
    assert (await client.get(verify)).text == "123"
    assert (await client.get(verify.replace("synthetic-verify-token", "bad"))).status_code == 403
    raw, signature = signed(inbound())
    assert (await client.post("/api/v1/webhooks/whatsapp", content=raw)).status_code == 403
    assert (
        await client.post("/api/v1/webhooks/whatsapp", content=raw + b" ", headers=signature)
    ).status_code == 403
    for _ in range(2):
        assert (
            await client.post("/api/v1/webhooks/whatsapp", content=raw, headers=signature)
        ).status_code == 200
    conversations = (await client.get("/api/v1/conversations", headers=a)).json()
    assert len(conversations) == 1 and conversations[0]["channel"] == "whatsapp"
    conversation_id = UUID(conversations[0]["id"])
    async with sessions() as session:
        assert len(await ConversationRepository(session, ctx).messages(conversation_id)) == 1
        stored = await ChannelRepository(session, ctx).get(UUID(account["id"]))
        assert "synthetic-provider-token" not in stored.credentials_encrypted
    assert (await client.get("/api/v1/conversations", headers=b)).json() == []
    assert len(app.state.jobs.jobs) == 2 and app.state.jobs.jobs[0] == app.state.jobs.jobs[1]
    raw, signature = signed(inbound("STOP", "wamid.stop"))
    assert (
        await client.post("/api/v1/webhooks/whatsapp", content=raw, headers=signature)
    ).status_code == 200
    consent = await client.get(
        "/api/v1/conversations/" + str(conversation_id) + "/whatsapp-consent", headers=a
    )
    assert consent.json()["opted_out"]
    assert (
        await client.get(
            "/api/v1/conversations/" + str(conversation_id) + "/whatsapp-consent", headers=b
        )
    ).status_code == 404
