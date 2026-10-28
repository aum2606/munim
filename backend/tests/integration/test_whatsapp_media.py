import httpx
import pytest

from tests.integration.test_whatsapp_webhooks import inbound, setup_channel, signed
from tests.integration.test_workspace import owner


@pytest.mark.parametrize("outcome", ["ok", "unsafe_host", "too_large"])
async def test_media_download_is_scoped_bounded_and_does_not_expose_meta_urls(client, outcome):
    auth, _, _, account = await setup_channel(client)
    other, _, _ = await owner(client)
    payload = inbound(
        kind="document",
        details={
            "document": {
                "id": "1234567",
                "filename": "../example.pdf",
                "mime_type": "application/pdf",
            }
        },
        phone_id=account["external_id"],
    )
    raw, signature = signed(payload)
    assert (
        await client.post("/api/v1/webhooks/whatsapp", content=raw, headers=signature)
    ).status_code == 200
    conversation_id = (await client.get("/api/v1/conversations", headers=auth)).json()[0]["id"]
    message_id = (
        await client.get("/api/v1/conversations/" + conversation_id + "/messages", headers=auth)
    ).json()[0]["id"]
    app = client._transport.app
    calls = []

    def respond(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-provider-token"
        if request.url.host == "graph.facebook.com":
            return httpx.Response(
                200,
                json={
                    "id": "1234567",
                    "url": "https://evil.example/private"
                    if outcome == "unsafe_host"
                    else "https://lookaside.fbsbx.com/whatsapp_business/attachments/?hash=synthetic-link",
                },
            )
        return httpx.Response(
            200, content=b"x" * 2048 if outcome == "too_large" else b"%PDF-synthetic"
        )

    app.state.whatsapp_transport = httpx.MockTransport(respond)
    app.state.settings.whatsapp_max_media_bytes = 1024
    path = f"/api/v1/conversations/{conversation_id}/messages/{message_id}/media/1234567"
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=other)).status_code == 404 and not calls
    assert (await client.get(path.replace("/1234567", "/7654321"), headers=auth)).status_code == 404
    result = await client.get(path, headers=auth)
    if outcome == "ok":
        assert result.status_code == 200 and result.content == b"%PDF-synthetic"
        assert result.headers["content-disposition"] == 'attachment; filename="example.pdf"'
        assert result.headers["x-content-type-options"] == "nosniff"
        assert b"synthetic-link" not in result.content
    else:
        assert result.status_code == (502 if outcome == "unsafe_host" else 413)
    assert all(
        request.url.host in {"graph.facebook.com", "lookaside.fbsbx.com"} for request in calls
    )
