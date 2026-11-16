"""The live inbox (take over, reply, hand back) and follow-up drafts."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update

from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import (
    Channel,
    Conversation,
    ConversationMode,
    Direction,
    FollowUp,
    Job,
    Quote,
    SenderType,
    User,
)
from app.db.session import SessionMaker
from app.jobs.handlers import build_handlers
from app.jobs.scheduler import enqueue_due_follow_ups
from app.llm.embedder import FakeEmbedder
from app.llm.fake import FakeLLM
from app.orchestrator.messages import canned
from app.orchestrator.pipeline import process_message
from app.orchestrator.pipeline_types import Deps
from app.repositories.chat import ChatRepository
from app.repositories.quotes import QuoteRepository
from app.services.followups import FollowUpService
from app.services.quotes import QuoteService
from seeds.data import PRINTING
from tests.conftest import PASSWORD, bearer, register
from tests.integration.test_quotes import Talk, collect, make_shop, mapping
from tests.integration.test_quotes import router as quote_router

EMBEDDER = FakeEmbedder()


def router(intent: str = "pricing") -> str:
    return json.dumps({"intent": intent, "language": "en", "script": "latin", "confidence": 0.9})


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


async def ask(
    client: httpx.AsyncClient, token: str, text: str, conversation: str | None = None
) -> str:
    sent = await client.post(
        "/api/v1/playground/messages",
        json={"text": text, "conversation_id": conversation},
        headers=bearer(token),
    )
    assert sent.status_code == 202
    return str(sent.json()["conversation_id"])


async def answer(
    sm: SessionMaker, settings: Settings, ctx: TenantContext, conversation: str, replies: list[str]
) -> FakeLLM:
    llm = FakeLLM(replies)
    await process_message(Deps(llm, EMBEDDER, settings, sm), ctx, {"conversation_id": conversation})
    return llm


async def tenant_of(client: httpx.AsyncClient, token: str) -> TenantContext:
    me = (await client.get("/api/v1/me", headers=bearer(token))).json()
    return TenantContext.system(uuid.UUID(me["tenant"]["id"]))


# --- take over, reply, hand back -------------------------------------------------------------


async def test_a_person_takes_over_replies_and_hands_back(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    _, token = await register(client)
    ctx = await tenant_of(client, token)
    conversation = await ask(client, token, "rate kya hai?")

    taken = await client.post(
        f"/api/v1/conversations/{conversation}/take-over", headers=bearer(token)
    )
    assert taken.status_code == 204
    listed = (await client.get("/api/v1/conversations?mode=human", headers=bearer(token))).json()
    assert [c["id"] for c in listed] == [conversation]
    assert listed[0]["last_message"] == "rate kya hai?"

    # The customer's message arrives while a person owns the chat: the AI says nothing.
    llm = await answer(sessionmaker, settings, ctx, conversation, [])
    assert llm.calls == []

    reply = await client.post(
        f"/api/v1/conversations/{conversation}/replies",
        json={"text": "Rs 250 per 100, sir."},
        headers=bearer(token),
    )
    assert reply.status_code == 201
    assert (reply.json()["sender_type"], reply.json()["content"]) == (
        "staff",
        "Rs 250 per 100, sir.",
    )

    # Hand back: the next customer message is answered by the assistant again.
    back = await client.post(
        f"/api/v1/conversations/{conversation}/return-to-ai", headers=bearer(token)
    )
    assert back.status_code == 204
    await ask(client, token, "and delivery?", conversation)
    await answer(sessionmaker, settings, ctx, conversation, [router(), not_grounded()])
    messages = (
        await client.get(f"/api/v1/conversations/{conversation}/messages", headers=bearer(token))
    ).json()
    assert [(m["sender_type"], m["content"]) for m in messages] == [
        ("customer", "rate kya hai?"),
        ("staff", "Rs 250 per 100, sir."),
        ("customer", "and delivery?"),
        ("ai", canned("confirm", "en")),
    ]


async def test_replying_takes_the_chat_over_so_the_ai_cannot_talk_over_the_person(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    _, token = await register(client)
    ctx = await tenant_of(client, token)
    conversation = await ask(client, token, "hello")
    await client.post(
        f"/api/v1/conversations/{conversation}/replies", json={"text": "Hi!"}, headers=bearer(token)
    )
    await ask(client, token, "rate?", conversation)
    llm = await answer(sessionmaker, settings, ctx, conversation, [])
    assert llm.calls == []
    async with sessionmaker() as session:
        stored = await ChatRepository(session, ctx).get_conversation(uuid.UUID(conversation))
    assert stored is not None and stored.mode == ConversationMode.HUMAN


async def test_inbox_actions_are_tenant_scoped_and_validated(client: httpx.AsyncClient) -> None:
    _, mine = await register(client)
    _, theirs = await register(client)
    conversation = await ask(client, mine, "hello")
    for path, body in (
        ("take-over", None),
        ("return-to-ai", None),
        ("replies", {"text": "hi"}),
    ):
        url = f"/api/v1/conversations/{conversation}/{path}"
        assert (await client.post(url, json=body, headers=bearer(theirs))).status_code == 404
        assert (await client.post(url, json=body)).status_code == 401
    other_inbox = await client.get("/api/v1/conversations", headers=bearer(theirs))
    assert other_inbox.json() == []
    for bad in ({"text": ""}, {"text": "x" * 2001}, {"text": "hi", "mode": "ai"}, {}):
        response = await client.post(
            f"/api/v1/conversations/{conversation}/replies", json=bad, headers=bearer(mine)
        )
        assert response.status_code == 422
    # Nothing leaked into the real conversation: still AI mode, one message.
    assert (await client.get("/api/v1/conversations?mode=ai", headers=bearer(mine))).json()[0][
        "id"
    ] == conversation


# --- follow-up drafts --------------------------------------------------------------------------


async def sent_quote(
    sm: SessionMaker, settings: Settings, *, days_ago: float, channel: Channel = Channel.PLAYGROUND
) -> tuple[TenantContext, uuid.UUID, uuid.UUID, str]:
    """A shop whose customer was sent a quote `days_ago` days ago and never replied.
    Returns the context, conversation id, quote id and the owner's login email."""
    ctx = await make_shop(sm, settings, PRINTING)
    async with sm() as session:
        owner_email = await session.scalar(
            select(User.email).where(User.tenant_id == ctx.tenant_id)
        )
    assert owner_email
    talk = Talk(sm, settings, ctx)
    await talk.say(
        "hello",
        [
            quote_router(),
            collect("printing", {}, ["What do you need?"]),
            json.dumps({"reply": "What do you need?"}),
        ],
    )
    await talk.say(
        "500 visiting cards, matt lamination please",
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
        ],
    )
    (quote,) = await talk.quotes()
    async with sm() as session:
        await QuoteService(session, ctx, settings).approve(quote.id)
        then = datetime.now(UTC) - timedelta(days=days_ago)
        await session.execute(update(Quote).where(Quote.id == quote.id).values(sent_at=then))
        await session.execute(
            update(Conversation)
            .where(Conversation.id == talk.cid)
            .values(last_customer_msg_at=then - timedelta(hours=1), channel=channel)
        )
        await session.commit()
    return ctx, talk.cid, quote.id, owner_email


async def login(client: httpx.AsyncClient, email: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return str(response.json()["access_token"])


async def drafts(sm: SessionMaker, ctx: TenantContext) -> list[FollowUp]:
    async with sm() as session:
        return list(
            await session.scalars(select(FollowUp).where(FollowUp.tenant_id == ctx.tenant_id))
        )


async def test_an_unanswered_quote_gets_one_draft_with_no_money_in_it(
    sessionmaker: SessionMaker, settings: Settings
) -> None:
    ctx, _, quote_id, _ = await sent_quote(sessionmaker, settings, days_ago=3)
    async with sessionmaker() as session:
        assert await FollowUpService(session, ctx, settings).generate() == 1
        assert await FollowUpService(session, ctx, settings).generate() == 0  # already drafted
        await session.commit()
        number = (await QuoteRepository(session, ctx).get(quote_id)).quote_number  # type: ignore[union-attr]
    (draft,) = await drafts(sessionmaker, ctx)
    assert number in draft.draft and "₹" not in draft.draft and draft.status == "draft"


async def test_no_draft_for_a_fresh_quote_or_one_the_customer_answered(
    sessionmaker: SessionMaker, settings: Settings
) -> None:
    fresh, *_ = await sent_quote(sessionmaker, settings, days_ago=0.5)
    answered, conversation, *_ = await sent_quote(sessionmaker, settings, days_ago=3)
    async with sessionmaker() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation)
            .values(last_customer_msg_at=datetime.now(UTC) - timedelta(days=1))
        )
        await session.commit()
        assert await FollowUpService(session, fresh, settings).generate() == 0
        assert await FollowUpService(session, answered, settings).generate() == 0


async def test_the_scheduler_queues_a_job_only_for_businesses_that_need_one(
    sessionmaker: SessionMaker, settings: Settings
) -> None:
    due, *_ = await sent_quote(sessionmaker, settings, days_ago=3)
    quiet, *_ = await sent_quote(sessionmaker, settings, days_ago=0.1)
    assert await enqueue_due_follow_ups(sessionmaker, settings) >= 1
    async with sessionmaker() as session:
        queued = {
            j.tenant_id
            for j in await session.scalars(select(Job).where(Job.kind == "create_follow_ups"))
        }
    assert due.tenant_id in queued and quiet.tenant_id not in queued

    handlers = build_handlers(EMBEDDER, settings, FakeLLM([]))
    await handlers["create_follow_ups"](sessionmaker, due, {})
    assert len(await drafts(sessionmaker, due)) == 1


async def test_follow_up_api_send_dismiss_and_isolation(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    ctx, conversation, _, email = await sent_quote(sessionmaker, settings, days_ago=3)
    token = await login(client, email)
    _, stranger = await register(client)
    async with sessionmaker() as session:
        await FollowUpService(session, ctx, settings).generate()
        await session.commit()

    assert (await client.get("/api/v1/follow-ups")).status_code == 401
    assert (await client.get("/api/v1/follow-ups", headers=bearer(stranger))).json() == []
    (item,) = (await client.get("/api/v1/follow-ups?status=draft", headers=bearer(token))).json()
    assert item["can_send"] is True and item["quote_number"] and item["customer_name"]

    url = f"/api/v1/follow-ups/{item['id']}"
    assert (await client.post(f"{url}/send", json={}, headers=bearer(stranger))).status_code == 404
    edited = await client.post(
        f"{url}/send", json={"text": "Hello, any update?"}, headers=bearer(token)
    )
    assert edited.status_code == 204
    async with sessionmaker() as session:
        last = (await ChatRepository(session, ctx).messages(conversation))[-1]
    assert (last.sender_type, last.content) == (SenderType.STAFF, "Hello, any update?")
    assert last.direction == Direction.OUT
    # Handled once: neither sending nor dismissing it again works.
    assert (await client.post(f"{url}/send", json={}, headers=bearer(token))).status_code == 409
    assert (await client.post(f"{url}/dismiss", headers=bearer(token))).status_code == 409
    assert (await client.get("/api/v1/follow-ups?status=draft", headers=bearer(token))).json() == []


async def test_dismissing_a_follow_up(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    ctx, _, _, email = await sent_quote(sessionmaker, settings, days_ago=3)
    token = await login(client, email)
    async with sessionmaker() as session:
        await FollowUpService(session, ctx, settings).generate()
        await session.commit()
    (item,) = (await client.get("/api/v1/follow-ups", headers=bearer(token))).json()
    assert (
        await client.post(f"/api/v1/follow-ups/{item['id']}/dismiss", headers=bearer(token))
    ).status_code == 204
    (after,) = (await client.get("/api/v1/follow-ups", headers=bearer(token))).json()
    assert after["status"] == "dismissed"


async def test_on_whatsapp_a_follow_up_after_24_hours_cannot_be_sent_from_here(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    ctx, _, _, email = await sent_quote(
        sessionmaker, settings, days_ago=3, channel=Channel.WHATSAPP
    )
    token = await login(client, email)
    async with sessionmaker() as session:
        await FollowUpService(session, ctx, settings).generate()
        await session.commit()
    (item,) = (await client.get("/api/v1/follow-ups", headers=bearer(token))).json()
    assert item["can_send"] is False  # WhatsApp would refuse: the owner copies it instead
    refused = await client.post(
        f"/api/v1/follow-ups/{item['id']}/send", json={}, headers=bearer(token)
    )
    assert refused.status_code == 409 and "24 hours" in refused.json()["error"]["message"]
    (after,) = (await client.get("/api/v1/follow-ups", headers=bearer(token))).json()
    assert after["status"] == "draft"  # still there to copy
