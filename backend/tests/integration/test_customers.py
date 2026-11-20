"""A customer's right of access and erasure: complete, scoped to one business, owner only."""

import uuid
from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import (
    AgentRun,
    AgentRunStatus,
    Channel,
    Conversation,
    Customer,
    Direction,
    KnowledgeGap,
    Lead,
    Message,
    Quote,
    SenderType,
)
from app.db.session import SessionMaker
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.chat import ChatRepository
from app.repositories.gaps import KnowledgeGapRepository
from tests.conftest import PASSWORD, bearer, register, unique_email
from tests.helpers import login
from tests.integration.test_inbox import sent_quote


async def count(sm: SessionMaker, model: type, ctx: TenantContext, *where: object) -> int:
    async with sm() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.tenant_id == ctx.tenant_id, *where)  # type: ignore[attr-defined]
            )
            or 0
        )


async def customer_of(sm: SessionMaker, conversation_id: uuid.UUID) -> uuid.UUID:
    async with sm() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        return conversation.customer_id


async def add_bystander(sm: SessionMaker, ctx: TenantContext) -> uuid.UUID:
    """Another customer of the same business, who must be untouched by the first one's erasure."""
    async with sm() as session:
        chat = ChatRepository(session, ctx)
        conversation = await chat.start_conversation(Channel.PLAYGROUND, "Bystander")
        message = await chat.add_message(
            conversation, direction=Direction.IN, sender_type=SenderType.CUSTOMER, content="hello"
        )
        await AgentRunRepository(session, ctx).add(
            agent="router",
            prompt_version="router@x",
            input={"text": "hello"},
            status=AgentRunStatus.OK,
            message_id=message.id,
        )
        await session.commit()
        return conversation.customer_id


async def test_erasing_a_customer_removes_everything_they_said_and_nothing_else(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    ctx, conversation, _, email = await sent_quote(sessionmaker, settings, days_ago=3)
    token = await login(client, email)
    target = await customer_of(sessionmaker, conversation)
    bystander = await add_bystander(sessionmaker, ctx)
    async with sessionmaker() as session:  # a knowledge gap that quotes the customer
        their_message = await session.scalar(
            select(Message).where(Message.conversation_id == conversation).limit(1)
        )
        assert their_message is not None
        await KnowledgeGapRepository(session, ctx).record("do you do embroidery", their_message.id)
        quote = await session.scalar(select(Quote).where(Quote.tenant_id == ctx.tenant_id))
        await session.commit()
    assert quote is not None and quote.pdf_path
    pdf = Path(settings.storage_dir) / quote.pdf_path
    assert pdf.exists()
    runs_before = await count(sessionmaker, AgentRun, ctx)
    assert runs_before > 1 and await count(sessionmaker, KnowledgeGap, ctx) == 1

    response = await client.delete(f"/api/v1/customers/{target}", headers=bearer(token))
    assert response.status_code == 204

    # Gone: the customer, their chats, leads, quotes, the model traces that hold their words,
    # the gap that quotes them, and the PDF on disk.
    assert await count(sessionmaker, Customer, ctx, Customer.id == target) == 0
    assert await count(sessionmaker, Conversation, ctx, Conversation.id == conversation) == 0
    assert await count(sessionmaker, Message, ctx, Message.conversation_id == conversation) == 0
    assert await count(sessionmaker, Lead, ctx, Lead.customer_id == target) == 0
    assert await count(sessionmaker, Quote, ctx) == 0
    assert await count(sessionmaker, KnowledgeGap, ctx) == 0
    assert not pdf.exists()
    # Kept: the other customer and their traces.
    assert await count(sessionmaker, Customer, ctx, Customer.id == bystander) == 1
    assert await count(sessionmaker, AgentRun, ctx) == 1  # only the bystander's trace is left

    assert (
        await client.delete(f"/api/v1/customers/{target}", headers=bearer(token))
    ).status_code == 404


async def test_export_returns_what_is_held_about_the_customer(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    ctx, conversation, _, email = await sent_quote(sessionmaker, settings, days_ago=3)
    token = await login(client, email)
    target = await customer_of(sessionmaker, conversation)

    found = await client.get("/api/v1/customers?q=asha", headers=bearer(token))
    assert [c["id"] for c in found.json()] == [str(target)]
    assert (await client.get("/api/v1/customers?q=zzz", headers=bearer(token))).json() == []

    exported = (
        await client.get(f"/api/v1/customers/{target}/export", headers=bearer(token))
    ).json()
    assert exported["customer"]["name"] == "Asha Traders"
    contents = [m["content"] for c in exported["conversations"] for m in c["messages"]]
    assert "500 visiting cards, matt lamination please" in contents
    (quote,) = exported["quotes"]
    assert quote["quote_number"].startswith("Q/") and quote["total_paise"] == 165200
    assert [i["line_total_paise"] for i in quote["items"]] == [117500, 22500]
    assert await count(sessionmaker, Customer, ctx, Customer.id == target) == 1


async def test_only_the_owner_of_that_business_can_export_or_erase(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    ctx, conversation, _, email = await sent_quote(sessionmaker, settings, days_ago=3)
    owner = await login(client, email)
    target = await customer_of(sessionmaker, conversation)
    _, stranger = await register(client)  # another business's owner

    for method, path in (
        ("GET", f"/api/v1/customers/{target}/export"),
        ("DELETE", f"/api/v1/customers/{target}"),
    ):
        assert (await client.request(method, path)).status_code == 401
        assert (await client.request(method, path, headers=bearer(stranger))).status_code == 404
    assert (await client.get("/api/v1/customers", headers=bearer(stranger))).json() == []

    staff_email = unique_email()
    created = await client.post(
        "/api/v1/users",
        json={"email": staff_email, "name": "Staff", "password": PASSWORD, "role": "staff"},
        headers=bearer(owner),
    )
    assert created.status_code == 201
    staff = await login(client, staff_email)
    for method, path in (
        ("GET", "/api/v1/customers"),
        ("GET", f"/api/v1/customers/{target}/export"),
        ("DELETE", f"/api/v1/customers/{target}"),
    ):
        assert (await client.request(method, path, headers=bearer(staff))).status_code == 403
    assert await count(sessionmaker, Customer, ctx, Customer.id == target) == 1  # nothing happened
