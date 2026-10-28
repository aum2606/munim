import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from app.channels.service import usable_template
from app.channels.whatsapp import GraphAmbiguous, GraphRejected, WhatsAppAdapter, WhatsAppGraph
from app.core.config import Settings
from app.db.models import Conversation
from app.db.models.conversation import ConversationStatus
from app.schemas.whatsapp import MetaMessage


def config():
    return Settings(
        whatsapp_api_version="v23.0", whatsapp_app_secret=SecretStr("synthetic-signing-secret")
    )


def test_raw_signature_and_exact_24_hour_boundary():
    adapter = WhatsAppAdapter(config())
    raw = b'{"synthetic": true}'
    signature = "sha256=" + hmac.new(b"synthetic-signing-secret", raw, hashlib.sha256).hexdigest()
    assert adapter.verify_webhook(raw, signature)
    assert not adapter.verify_webhook(raw + b" ", signature)
    assert not adapter.verify_webhook(raw, "wrong")
    assert not adapter.verify_webhook(raw, "sha256=é")
    now = datetime.now(UTC)
    conversation = Conversation(
        status=ConversationStatus.OPEN, last_customer_msg_at=now - timedelta(hours=24)
    )
    assert not adapter.can_send_freeform(conversation, now)
    conversation.last_customer_msg_at += timedelta(seconds=1)
    assert adapter.can_send_freeform(conversation, now)
    conversation.last_customer_msg_at = now + timedelta(seconds=1)
    assert not adapter.can_send_freeform(conversation, now)


@pytest.mark.parametrize(
    "kind,details,expected",
    [
        ("text", {"text": {"body": "Hello"}}, "text"),
        (
            "interactive",
            {"interactive": {"button_reply": {"id": "help", "title": "Human please"}}},
            "text",
        ),
        ("button", {"button": {"text": "Request a quote"}}, "text"),
        ("image", {"image": {"id": "123", "caption": "Review please"}}, "media"),
        ("document", {"document": {"id": "456", "filename": "../quote.pdf"}}, "media"),
        ("audio", {}, "unsupported"),
    ],
)
def test_inbound_types_remain_bounded_untrusted_content(kind, details, expected):
    message = MetaMessage.model_validate(
        {
            "id": "wamid.synthetic",
            "from": "919000000001",
            "timestamp": str(int(datetime.now(UTC).timestamp())),
            "type": kind,
            **details,
        }
    )
    parsed = WhatsAppAdapter(config()).parse_inbound(message)
    assert parsed.content_type == expected
    if kind == "document":
        assert parsed.attachments[0]["filename"] == "quote.pdf"


def test_template_requires_approved_static_money_free_body():
    approved = {"status": "APPROVED", "components": [{"type": "BODY", "text": "Can we help?"}]}
    assert usable_template(approved) == ("Can we help?", True)
    assert not usable_template({**approved, "status": "PAUSED"})[1]
    for text in ["Hello {{1}}", "Price INR 10", "", "₹450"]:
        assert not usable_template({**approved, "components": [{"type": "BODY", "text": text}]})[1]


async def test_graph_wire_contract_and_redacted_errors():
    seen = []

    def respond(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-access-token"
        if request.url.path.endswith("/media"):
            assert b"application/pdf" in request.content and b"%PDF-synthetic" in request.content
            return httpx.Response(200, json={"id": "12345"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.outbound"}]})

    graph = WhatsAppGraph(config(), "synthetic-access-token", httpx.MockTransport(respond))
    assert await graph.upload_pdf("12345", b"%PDF-synthetic") == "12345"
    assert (
        await graph.send(
            "12345",
            {"messaging_product": "whatsapp", "type": "document", "document": {"id": "12345"}},
        )
        == "wamid.outbound"
    )
    assert seen[-1].url.path == "/v23.0/12345/messages"
    bad = WhatsAppGraph(
        config(),
        "synthetic",
        httpx.MockTransport(
            lambda _: httpx.Response(
                401,
                headers={"Retry-After": "45"},
                json={"error": {"code": 190, "message": "sensitive-provider-detail"}},
            )
        ),
    )
    with pytest.raises(GraphRejected) as failure:
        await bad.send("12345", {})
    assert failure.value.code == "190" and "sensitive" not in str(failure.value)
    assert failure.value.retry_after == 45
    malformed = WhatsAppGraph(
        config(), "synthetic", httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    )
    with pytest.raises(GraphAmbiguous):
        await malformed.send("12345", {})
