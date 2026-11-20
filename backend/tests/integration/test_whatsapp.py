"""WhatsApp end to end with a fake Meta: webhooks in, jobs, replies out. No network, no real model,
no real speech model."""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update

from app.core.config import Settings
from app.core.context import TenantContext
from app.core.crypto import encrypt_credentials
from app.db.models import (
    ChannelAccount,
    Conversation,
    ConversationMode,
    Direction,
    Job,
    JobStatus,
    Message,
    SenderType,
)
from app.db.session import SessionMaker
from app.jobs.handlers import build_handlers
from app.jobs.queue import mark_done, mark_failed
from app.llm.embedder import FakeEmbedder
from app.llm.fake import FakeLLM
from app.llm.transcriber import FakeTranscriber, Transcription
from app.orchestrator.messages import canned, voice_confirm_message
from app.repositories.channels import ChannelAccountRepository
from app.repositories.chat import ChatRepository
from app.repositories.quotes import QuoteRepository
from app.services.quotes import QuoteService
from seeds.data import PRINTING
from tests.conftest import PASSWORD, bearer, register, unique_email
from tests.integration.test_quotes import collect, make_shop, mapping
from tests.integration.test_quotes import router as quote_router

SECRET = "meta-app-secret"
VERIFY = "verify-me"
PHONE = "919876543210"
TOKEN = "EAAG" + "x" * 40  # a fake access token
EMBEDDER = FakeEmbedder()


def fresh_number() -> str:
    """Meta phone number ids are digits."""
    return str(uuid.uuid4().int % 10**15 + 10**15)


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "whatsapp_verify_token": VERIFY,
            "whatsapp_app_secret": SECRET,
            "debounce_seconds": 0.0,
            "customer_messages_per_10_min": 4,
        }
    )


class FakeMeta:
    """Stands in for graph.facebook.com: records what we send and serves media."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.audio = b"OggS-fake-voice-note"
        self.fail_status: int | None = None
        self._counter = 0
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.fail_status:  # refused calls are not recorded: `requests` is what Meta accepted
            return httpx.Response(self.fail_status, json={"error": {"type": "X", "code": 1}})
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "lookaside.fbsbx.com":
            return httpx.Response(200, content=self.audio)
        if request.method == "GET":  # media metadata
            url = "https://lookaside.fbsbx.com/audio"
            return httpx.Response(
                200, json={"url": url, "mime_type": "audio/ogg", "file_size": len(self.audio)}
            )
        if path.endswith("/media"):
            return httpx.Response(200, json={"id": "UPLOADED-1"})
        self._counter += 1
        return httpx.Response(200, json={"messages": [{"id": f"wamid.OUT{self._counter}"}]})

    def sent(self) -> list[dict[str, object]]:
        """Bodies of everything sent to /messages, in order."""
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/messages")]

    def uploads(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith("/media") and r.method == "POST"]


@dataclass
class Env:
    client: httpx.AsyncClient
    sm: SessionMaker
    settings: Settings
    ctx: TenantContext
    token: str
    meta: FakeMeta = field(default_factory=FakeMeta)
    transcriptions: list[Transcription] = field(default_factory=list)

    async def jobs(self, replies: list[str] | None = None) -> FakeLLM:
        """Run this business's due jobs the way the worker would (other tests' jobs are left)."""
        llm = FakeLLM(replies or [])
        handlers = build_handlers(
            EMBEDDER, self.settings, llm, self.meta.http, FakeTranscriber(self.transcriptions)
        )
        for _ in range(20):
            async with self.sm() as session:
                due = list(
                    await session.scalars(
                        select(Job)
                        .where(
                            Job.tenant_id == self.ctx.tenant_id,
                            Job.status == JobStatus.QUEUED,
                            Job.run_at <= datetime.now(UTC),
                        )
                        .order_by(Job.created_at)
                    )
                )
                if not due:
                    break
                for job in due:
                    job.attempts += 1
                    try:
                        await handlers[job.kind](self.sm, self.ctx, job.payload)
                    except Exception as exc:
                        await mark_failed(session, job.id, type(exc).__name__)
                    else:
                        await mark_done(session, job.id)
                await session.commit()
        return llm

    async def messages(self) -> list[Message]:
        async with self.sm() as session:
            conversation = await session.scalar(
                select(Conversation).where(Conversation.tenant_id == self.ctx.tenant_id)
            )
            assert conversation is not None
            return await ChatRepository(session, self.ctx).messages(conversation.id)

    async def conversation(self) -> Conversation:
        async with self.sm() as session:
            conversation = await session.scalar(
                select(Conversation).where(Conversation.tenant_id == self.ctx.tenant_id)
            )
            assert conversation is not None
            return conversation


async def connect(client: httpx.AsyncClient, token: str, number_id: str) -> httpx.Response:
    return await client.put(
        "/api/v1/channels/whatsapp",
        json={
            "phone_number_id": number_id,
            "display_phone": "+1 555 000 1111",
            "access_token": TOKEN,
        },
        headers=bearer(token),
    )


async def new_env(
    client: httpx.AsyncClient, sm: SessionMaker, settings: Settings, number_id: str
) -> Env:
    _, token = await register(client)
    me = (await client.get("/api/v1/me", headers=bearer(token))).json()
    assert (await connect(client, token, number_id)).status_code == 200
    return Env(client, sm, settings, TenantContext.system(uuid.UUID(me["tenant"]["id"])), token)


@pytest.fixture
async def env(client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings) -> Env:
    return await new_env(client, sessionmaker, settings, fresh_number())


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def event(
    number_id: str,
    *,
    messages: list[dict[str, object]] | None = None,
    statuses: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550001111", "phone_number_id": number_id},
        "contacts": [{"profile": {"name": "Asha"}, "wa_id": PHONE}],
    }
    if messages:
        value["messages"] = messages
    if statuses:
        value["statuses"] = statuses
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": value}]}],
    }


def text_in(wamid: str, body: str) -> dict[str, object]:
    return {
        "from": PHONE,
        "id": wamid,
        "timestamp": "1700000000",
        "type": "text",
        "text": {"body": body},
    }


def voice_in(wamid: str) -> dict[str, object]:
    return {
        "from": PHONE,
        "id": wamid,
        "timestamp": "1700000000",
        "type": "audio",
        "audio": {"id": "MEDIA-1", "mime_type": "audio/ogg; codecs=opus", "voice": True},
    }


async def deliver(client: httpx.AsyncClient, payload: dict[str, object]) -> httpx.Response:
    body = json.dumps(payload).encode()
    return await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": sign(body), "Content-Type": "application/json"},
    )


def router(intent: str = "pricing", **extra: object) -> str:
    return json.dumps(
        {"intent": intent, "language": "en", "script": "latin", "confidence": 0.9, **extra}
    )


def not_grounded() -> str:
    return json.dumps(
        {
            "answer_points": [],
            "cited_item_ids": [],
            "price_item_ids": [],
            "grounded": False,
            "gap_question": "rate?",
        }
    )


CONFIRM_REPLIES = [router(), not_grounded()]  # a turn that ends in the fixed "I'll confirm" reply


# --- the subscription check ------------------------------------------------------------------


async def test_meta_subscription_check(client: httpx.AsyncClient) -> None:
    ok = await client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1158201444"},
    )
    assert (ok.status_code, ok.text) == (200, "1158201444")
    bad = await client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"},
    )
    assert bad.status_code == 403


async def test_a_webhook_with_a_bad_or_missing_signature_is_refused(
    env: Env, client: httpx.AsyncClient
) -> None:
    payload = event(await _number(env), messages=[text_in("wamid.EVIL", "hi")])
    body = json.dumps(payload).encode()
    for headers in (
        {"X-Hub-Signature-256": sign(body, "wrong-secret")},
        {"X-Hub-Signature-256": "sha256=deadbeef"},
        {},
    ):
        response = await client.post("/webhooks/whatsapp", content=body, headers=headers)
        assert response.status_code == 403
    assert await _count(env, Message) == 0


async def test_malformed_and_oversized_webhooks_are_rejected(client: httpx.AsyncClient) -> None:
    junk = b"not json"
    response = await client.post(
        "/webhooks/whatsapp", content=junk, headers={"X-Hub-Signature-256": sign(junk)}
    )
    assert response.status_code == 422
    big = b"x" * (3 * 1024 * 1024 + 1)
    response = await client.post(
        "/webhooks/whatsapp", content=big, headers={"X-Hub-Signature-256": sign(big)}
    )
    assert response.status_code == 422


# --- text messages ---------------------------------------------------------------------------


async def test_a_text_message_is_answered_and_the_reply_is_delivered(env: Env) -> None:
    number = await _number(env)
    response = await deliver(
        env.client, event(number, messages=[text_in("wamid.IN1", "rate kya hai?")])
    )
    assert response.status_code == 200

    await env.jobs(CONFIRM_REPLIES)

    incoming, reply = await env.messages()
    assert (incoming.direction, incoming.content, incoming.external_id) == (
        Direction.IN,
        "rate kya hai?",
        "wamid.IN1",
    )
    assert reply.sender_type == SenderType.AI and reply.content == canned("confirm", "en")
    assert (reply.external_id, reply.delivery_status) == ("wamid.OUT1", "sent")
    (sent,) = env.meta.sent()
    assert sent["to"] == PHONE and sent["text"] == {"body": reply.content}
    assert env.meta.requests[0].headers["Authorization"] == f"Bearer {TOKEN}"

    inbox = (await env.client.get("/api/v1/conversations", headers=bearer(env.token))).json()
    assert (inbox[0]["customer_name"], inbox[0]["customer_phone"]) == ("Asha", f"+{PHONE}")
    assert inbox[0]["channel"] == "whatsapp" and inbox[0]["can_reply"] is True


async def test_a_webhook_delivered_twice_is_stored_and_answered_once(env: Env) -> None:
    number = await _number(env)
    payload = event(number, messages=[text_in("wamid.DUP", "rate kya hai?")])
    assert (await deliver(env.client, payload)).status_code == 200
    assert (await deliver(env.client, payload)).status_code == 200  # Meta retried

    await env.jobs(CONFIRM_REPLIES)

    assert len(await env.messages()) == 2  # one inbound, one reply
    assert len(env.meta.sent()) == 1


async def test_delivery_statuses_only_move_forward(env: Env) -> None:
    number = await _number(env)
    await deliver(env.client, event(number, messages=[text_in("wamid.IN2", "rate?")]))
    await env.jobs(CONFIRM_REPLIES)

    async def status(name: str) -> None:
        r = await deliver(
            env.client, event(number, statuses=[{"id": "wamid.OUT1", "status": name}])
        )
        assert r.status_code == 200

    await status("delivered")
    await status("read")
    await status("sent")  # arrives late: must not undo "read"
    assert (await env.messages())[-1].delivery_status == "read"


async def test_a_failed_status_records_why(env: Env) -> None:
    number = await _number(env)
    await deliver(env.client, event(number, messages=[text_in("wamid.IN3", "rate?")]))
    await env.jobs(CONFIRM_REPLIES)
    await deliver(
        env.client,
        event(
            number,
            statuses=[{"id": "wamid.OUT1", "status": "failed", "errors": [{"title": "Blocked"}]}],
        ),
    )
    last = (await env.messages())[-1]
    assert (last.delivery_status, last.delivery_error) == ("failed", "Blocked")


async def test_a_message_to_an_unknown_number_is_ignored(env: Env) -> None:
    response = await deliver(
        env.client, event("NOT-CONNECTED", messages=[text_in("wamid.X", "hi")])
    )
    assert response.status_code == 200
    assert await _count(env, Message) == 0


async def test_an_image_gets_a_polite_reply_and_no_model_call(env: Env) -> None:
    number = await _number(env)
    image = {"from": PHONE, "id": "wamid.IMG", "type": "image", "image": {"id": "I1"}}
    await deliver(env.client, event(number, messages=[image]))
    llm = await env.jobs()
    assert llm.calls == []
    incoming, reply = await env.messages()
    assert incoming.handled_at is not None
    assert reply.content == canned("unsupported", "en") and reply.delivery_status == "sent"


async def test_a_complaint_hands_over_and_the_ai_stays_silent_afterwards(env: Env) -> None:
    number = await _number(env)
    await deliver(env.client, event(number, messages=[text_in("wamid.C1", "my order is damaged!")]))
    await env.jobs([router("complaint", sentiment="negative")])
    assert (await env.conversation()).mode == ConversationMode.HUMAN
    assert (await env.messages())[-1].content == canned("handoff", "en")

    await deliver(env.client, event(number, messages=[text_in("wamid.C2", "hello? anyone there?")]))
    llm = await env.jobs([])
    assert llm.calls == []  # no model is even consulted
    messages = await env.messages()
    assert [m.direction for m in messages] == [Direction.IN, Direction.OUT, Direction.IN]
    assert messages[-1].handled_at is not None
    assert len(env.meta.sent()) == 1  # only the handoff notice ever went out
    human = await env.client.get("/api/v1/conversations?mode=human", headers=bearer(env.token))
    assert len(human.json()) == 1


async def test_one_chat_flooding_the_bot_is_stored_but_not_answered(env: Env) -> None:
    number = await _number(env)
    for n in range(1, 5):  # within the allowance: answered like any other batch
        await deliver(env.client, event(number, messages=[text_in(f"wamid.FL{n}", f"q{n}")]))
    await env.jobs(CONFIRM_REPLIES)
    answered = len(env.meta.sent())
    for n in range(5, 12):  # past it
        await deliver(env.client, event(number, messages=[text_in(f"wamid.FL{n}", f"q{n}")]))
    llm = await env.jobs([])

    assert llm.calls == [] and len(env.meta.sent()) == answered  # no model call, nothing sent
    messages = await env.messages()
    flooded = [
        m
        for m in messages
        if m.direction == Direction.IN and int((m.external_id or "").removeprefix("wamid.FL")) >= 5
    ]
    assert len(flooded) == 7 and all(
        m.handled_at is not None for m in flooded
    )  # kept for the owner


# --- delivery edge cases -----------------------------------------------------------------------


async def test_nothing_is_sent_after_the_24_hour_window(env: Env) -> None:
    number = await _number(env)
    await deliver(env.client, event(number, messages=[text_in("wamid.W1", "rate?")]))
    await env.jobs([])  # no model: the message is handled but we only care about the window
    conversation = await env.conversation()
    async with env.sm() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(last_customer_msg_at=datetime.now(UTC) - timedelta(hours=25))
        )
        repo = ChatRepository(session, env.ctx)
        fresh = await repo.get_conversation(conversation.id)
        assert fresh is not None
        late = await repo.add_message(
            fresh, direction=Direction.OUT, sender_type=SenderType.STAFF, content="Late reply"
        )
        await session.commit()
    env.meta.requests.clear()

    await env.jobs()

    assert env.meta.requests == []
    async with env.sm() as session:
        stored = await ChatRepository(session, env.ctx).get_message(late.id)
    assert stored is not None and stored.delivery_status == "window_closed"
    inbox = (await env.client.get("/api/v1/conversations", headers=bearer(env.token))).json()
    assert inbox[0]["can_reply"] is False


async def test_a_permanent_error_marks_the_message_failed_without_retrying(env: Env) -> None:
    number = await _number(env)
    await deliver(env.client, event(number, messages=[text_in("wamid.F1", "rate?")]))
    env.meta.fail_status = 401  # expired token
    await env.jobs(CONFIRM_REPLIES)
    reply = (await env.messages())[-1]
    assert (reply.delivery_status, reply.delivery_error) == ("failed", "X 1")
    assert reply.external_id is None
    async with env.sm() as session:
        statuses = {
            j.status
            for j in await session.scalars(select(Job).where(Job.tenant_id == env.ctx.tenant_id))
        }
    assert statuses == {JobStatus.DONE}


async def test_a_temporary_error_is_retried_and_never_double_sends(env: Env) -> None:
    number = await _number(env)
    await deliver(env.client, event(number, messages=[text_in("wamid.F2", "rate?")]))
    env.meta.fail_status = 503
    await env.jobs(CONFIRM_REPLIES)
    assert (await env.messages())[-1].delivery_status is None
    async with env.sm() as session:
        job = await session.scalar(
            select(Job).where(Job.tenant_id == env.ctx.tenant_id, Job.kind == "deliver_message")
        )
        assert job is not None and job.status == JobStatus.QUEUED and job.attempts == 1
        job.run_at = datetime.now(UTC)  # skip the backoff wait
        await session.commit()

    env.meta.fail_status = None
    await env.jobs()
    await env.jobs()  # running again must not send again
    assert (await env.messages())[-1].delivery_status == "sent"
    assert len(env.meta.sent()) == 1


async def test_a_disconnected_number_stops_receiving(env: Env) -> None:
    number = await _number(env)
    deleted = await env.client.delete("/api/v1/channels/whatsapp", headers=bearer(env.token))
    assert deleted.status_code == 204
    await deliver(env.client, event(number, messages=[text_in("wamid.G1", "hi")]))
    assert await _count(env, Message) == 0


# --- staff replies over WhatsApp -----------------------------------------------------------------


async def test_a_staff_reply_is_delivered_and_the_ai_then_stays_silent(env: Env) -> None:
    number = await _number(env)
    await deliver(env.client, event(number, messages=[text_in("wamid.S1", "need a discount")]))
    await env.jobs(CONFIRM_REPLIES)
    conversation = (await env.conversation()).id

    reply = await env.client.post(
        f"/api/v1/conversations/{conversation}/replies",
        json={"text": "Sure, call me."},
        headers=bearer(env.token),
    )
    assert reply.status_code == 201
    await env.jobs()
    assert env.meta.sent()[-1]["text"] == {"body": "Sure, call me."}
    assert (await env.messages())[-1].delivery_status == "sent"

    await deliver(env.client, event(number, messages=[text_in("wamid.S2", "thanks")]))
    llm = await env.jobs([])
    assert llm.calls == [] and len(env.meta.sent()) == 2


async def test_a_staff_reply_is_refused_after_the_24_hour_window(env: Env) -> None:
    number = await _number(env)
    await deliver(env.client, event(number, messages=[text_in("wamid.S3", "hi")]))
    await env.jobs(CONFIRM_REPLIES)
    conversation = await env.conversation()
    async with env.sm() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(last_customer_msg_at=datetime.now(UTC) - timedelta(hours=30))
        )
        await session.commit()
    refused = await env.client.post(
        f"/api/v1/conversations/{conversation.id}/replies",
        json={"text": "Sorry for the delay"},
        headers=bearer(env.token),
    )
    assert refused.status_code == 409 and "24 hours" in refused.json()["error"]["message"]
    assert (await env.messages())[-1].sender_type == SenderType.AI  # nothing was stored


# --- voice notes -----------------------------------------------------------------------------


async def test_a_clear_voice_note_is_transcribed_and_answered_like_text(env: Env) -> None:
    number = await _number(env)
    env.transcriptions = [Transcription("visiting card ka rate kya hai", "hi", 0.92)]
    await deliver(env.client, event(number, messages=[voice_in("wamid.V1")]))

    await env.jobs(CONFIRM_REPLIES)

    voice, reply = await env.messages()
    assert voice.kind == "audio" and voice.content == "visiting card ka rate kya hai"
    assert voice.transcript_confidence == pytest.approx(0.92)
    assert voice.handled_at is not None
    assert reply.content == canned("confirm", "en")
    # The audio was fetched with the business's own token.
    assert any(r.url.host == "lookaside.fbsbx.com" for r in env.meta.requests)


async def test_a_doubtful_voice_note_asks_the_customer_to_confirm(env: Env) -> None:
    number = await _number(env)
    env.transcriptions = [Transcription("five hundred kaard", "hi", 0.31)]
    await deliver(env.client, event(number, messages=[voice_in("wamid.V2")]))

    llm = await env.jobs()

    assert llm.calls == []  # we do not act on words we are not sure of
    voice, reply = await env.messages()
    assert voice.content == "five hundred kaard" and voice.handled_at is not None
    assert reply.content == voice_confirm_message("hinglish", "five hundred kaard")
    assert reply.delivery_status == "sent"


async def test_an_unintelligible_voice_note_asks_for_text(env: Env) -> None:
    number = await _number(env)
    env.transcriptions = [Transcription("", "en", 0.0)]
    await deliver(env.client, event(number, messages=[voice_in("wamid.V3")]))
    llm = await env.jobs()
    assert llm.calls == []
    assert (await env.messages())[-1].content == canned("voice_failed", "en")


async def test_a_voice_note_that_cannot_be_downloaded_asks_for_text(env: Env) -> None:
    number = await _number(env)
    await deliver(env.client, event(number, messages=[voice_in("wamid.V4")]))
    env.meta.fail_status = 404  # the media id expired
    await env.jobs()
    assert (await env.messages())[-1].content == canned("voice_failed", "en")


async def test_a_speech_model_crash_asks_for_text_instead_of_retrying_forever(env: Env) -> None:
    number = await _number(env)
    env.transcriptions = []  # the fake raises when it has nothing to return
    await deliver(env.client, event(number, messages=[voice_in("wamid.V6")]))
    await env.jobs()
    assert (await env.messages())[-1].content == canned("voice_failed", "en")


async def test_a_reply_after_the_number_was_disconnected_is_marked_failed(env: Env) -> None:
    number = await _number(env)
    await deliver(env.client, event(number, messages=[text_in("wamid.D1", "hi")]))
    await env.jobs(CONFIRM_REPLIES)
    await env.client.delete("/api/v1/channels/whatsapp", headers=bearer(env.token))
    conversation = await env.conversation()
    reply = await env.client.post(
        f"/api/v1/conversations/{conversation.id}/replies",
        json={"text": "Hello"},
        headers=bearer(env.token),
    )
    assert reply.status_code == 201
    await env.jobs()
    last = (await env.messages())[-1]
    assert (last.delivery_status, last.delivery_error) == ("failed", "no_whatsapp_account")


async def test_a_voice_note_is_only_transcribed_once(env: Env) -> None:
    number = await _number(env)
    env.transcriptions = [Transcription("rate kya hai", "hi", 0.9)]
    await deliver(env.client, event(number, messages=[voice_in("wamid.V5")]))
    await env.jobs(CONFIRM_REPLIES)
    handlers = build_handlers(
        EMBEDDER, env.settings, FakeLLM([]), env.meta.http, FakeTranscriber([])
    )
    voice = (await env.messages())[0]
    await handlers["transcribe_message"](
        env.sm, env.ctx, {"message_id": str(voice.id)}
    )  # no 2nd result queued
    assert len(await env.messages()) == 2


# --- tenancy ---------------------------------------------------------------------------------


async def test_businesses_only_receive_their_own_numbers_messages(
    env: Env, client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    other = await new_env(client, sessionmaker, settings, fresh_number())
    await deliver(client, event(await _number(env), messages=[text_in("wamid.T1", "hello A")]))
    await deliver(client, event(await _number(other), messages=[text_in("wamid.T2", "hello B")]))

    assert [m.content for m in await env.messages()] == ["hello A"]
    assert [m.content for m in await other.messages()] == ["hello B"]
    mine = (await client.get("/api/v1/conversations", headers=bearer(env.token))).json()
    assert len(mine) == 1


async def test_the_same_message_id_in_two_businesses_is_not_a_duplicate(
    env: Env, client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    other = await new_env(client, sessionmaker, settings, fresh_number())
    await deliver(client, event(await _number(env), messages=[text_in("wamid.SAME", "A")]))
    await deliver(client, event(await _number(other), messages=[text_in("wamid.SAME", "B")]))
    assert len(await env.messages()) == 1 and len(await other.messages()) == 1


# --- connecting a number -----------------------------------------------------------------------


async def test_connecting_stores_the_token_encrypted_and_never_returns_it(
    client: httpx.AsyncClient, sessionmaker: SessionMaker
) -> None:
    _, token = await register(client)
    assert (await client.get("/api/v1/channels/whatsapp", headers=bearer(token))).json() == {
        "connected": False,
        "phone_number_id": None,
        "display_phone": None,
        "webhook_ready": True,
    }
    response = await connect(client, token, "110000000000001")
    assert response.status_code == 200 and TOKEN not in response.text
    assert response.json()["connected"] and response.json()["phone_number_id"] == "110000000000001"
    async with sessionmaker() as session:
        row = await session.scalar(
            select(ChannelAccount).where(ChannelAccount.external_id == "110000000000001")
        )
    assert row is not None and TOKEN not in row.credentials_encrypted


async def test_connecting_needs_a_signed_in_owner_and_valid_input(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get("/api/v1/channels/whatsapp")).status_code == 401
    assert (await client.put("/api/v1/channels/whatsapp", json={})).status_code == 401
    _, owner = await register(client)
    bad = await client.put(
        "/api/v1/channels/whatsapp",
        json={"phone_number_id": "not digits!", "access_token": TOKEN},
        headers=bearer(owner),
    )
    assert bad.status_code == 422

    email = unique_email()
    created = await client.post(
        "/api/v1/users",
        json={"email": email, "name": "Staff", "password": PASSWORD, "role": "staff"},
        headers=bearer(owner),
    )
    assert created.status_code == 201
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    staff = login.json()["access_token"]
    assert (await connect(client, staff, "110000000000002")).status_code == 403
    assert (
        await client.delete("/api/v1/channels/whatsapp", headers=bearer(staff))
    ).status_code == 403


async def test_a_number_cannot_be_connected_to_two_businesses(
    client: httpx.AsyncClient,
) -> None:
    _, first = await register(client)
    _, second = await register(client)
    number = fresh_number()
    assert (await connect(client, first, number)).status_code == 200
    assert (await connect(client, second, number)).status_code == 409
    assert (await connect(client, first, number)).status_code == 200  # re-saving your own is fine
    status = await client.get("/api/v1/channels/whatsapp", headers=bearer(second))
    assert status.json()["connected"] is False


# --- acceptance: a Hinglish voice note to an approved PDF on WhatsApp ----------------------------


async def test_voice_note_to_approved_quotation_pdf_delivered_on_whatsapp(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    ctx = await make_shop(sessionmaker, settings, replace(PRINTING, owner_email=unique_email()))
    number = fresh_number()
    async with sessionmaker() as session:
        await ChannelAccountRepository(session, ctx).save(
            number, "+1 555", encrypt_credentials(settings, {"access_token": TOKEN})
        )
        await session.commit()
    env = Env(client, sessionmaker, settings, ctx, "")
    env.transcriptions = [
        Transcription("mujhe 500 visiting cards chahiye, matt lamination ke saath", "hi", 0.9)
    ]

    # 1. The customer sends a voice note.
    assert (
        await deliver(client, event(number, messages=[voice_in("wamid.Q1")]))
    ).status_code == 200
    await env.jobs(
        [
            quote_router(),
            collect(
                "printing",
                {"item_type": "visiting card", "quantity": "500", "finishing": "matt lamination"},
            ),
            mapping(
                {
                    "sku": "VC-STD",
                    "description": "Visiting card",
                    "quantity": 500,
                    "addon_codes": ["LAM-MATT"],
                }
            ),
        ]
    )

    # 2. They are told a quote is coming, and shown no price: the owner has not approved yet.
    voice, reply = await env.messages()
    assert voice.content.startswith("mujhe 500 visiting cards")
    assert reply.content == canned("quote_pending", "en") and reply.delivery_status == "sent"
    assert all("₹" not in str(body) for body in env.meta.sent())
    assert env.meta.uploads() == []

    # 3. The owner approves; the customer receives the PDF as a WhatsApp document.
    async with sessionmaker() as session:
        (quote_id,) = [q.id for q in await QuoteRepository(session, ctx).browse()]
        await QuoteService(session, ctx, settings).approve(quote_id)
        await session.commit()
    await env.jobs()

    (upload,) = env.meta.uploads()
    assert b"%PDF" in upload.content
    document = env.meta.sent()[-1]
    assert document["type"] == "document" and document["to"] == PHONE
    detail = document["document"]
    assert isinstance(detail, dict) and detail["id"] == "UPLOADED-1"
    assert str(detail["filename"]).endswith(".pdf")
    assert "₹1,652.00" in str(detail["caption"])  # the owner-approved total, from the engine
    assert (await env.messages())[-1].delivery_status == "sent"


# --- helpers -----------------------------------------------------------------------------------


async def _number(env: Env) -> str:
    async with env.sm() as session:
        account = await ChannelAccountRepository(session, env.ctx).get()
    assert account is not None
    return account.external_id


async def _count(env: Env, model: type[Message]) -> int:
    async with env.sm() as session:
        rows = await session.scalars(select(model).where(model.tenant_id == env.ctx.tenant_id))
        return len(list(rows))
