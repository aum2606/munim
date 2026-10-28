from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.analytics.events import emit
from app.analytics.service import InsightsService, digest_window
from app.core.errors import NotFound
from app.db.models import CatalogItem, Conversation, Customer, Handoff, Lead, Message, Quote
from app.db.models.analytics import AnalyticsEvent, WeeklyDigest
from app.db.models.analytics import AnalyticsEventType as Event
from app.db.models.conversation import ConversationStatus, Direction, SenderType
from app.db.models.lead import LeadStage
from app.db.models.quote import QuoteStatus
from app.llm import FakeEmbedder, FakeLLM
from app.llm.offline import agent_response
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.analytics import AnalyticsRepository, DigestRepository, period_bounds
from app.repositories.conversations import ConversationRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.insights import AnalyticsTool as Tool
from app.schemas.insights import InsightPlan, InsightQuestion, Period
from app.tools.analytics import AnalyticsTools
from tests.integration.test_workspace import owner

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


async def seed_analytics(session, ctx, now=NOW):
    """Synthetic facts with hand-counted expectations; never customer data or real APIs."""
    conversations = []
    for index, days in enumerate([3, 1, 2, 2, 2, 2, 40]):
        customer = await ScopedRepository(session, ctx, Customer).create(
            name=f"Demo customer {index}"
        )
        conversation = await ScopedRepository(session, ctx, Conversation).create(
            customer_id=customer.id, channel="web" if index % 2 == 0 else "whatsapp"
        )
        first = now - timedelta(days=days)
        message = await ConversationRepository(session, ctx).receive(
            conversation.id, "Synthetic enquiry", str(uuid4()), received_at=first
        )
        message.intent = "pricing" if index % 2 == 0 else "general_faq"
        conversation.last_customer_msg_at = first
        if index != 1:
            reply_at = first + timedelta(seconds=[86400, 0, 10, 30, 60, 20, 100][index])
            await ScopedRepository(session, ctx, Message).create(
                conversation_id=conversation.id,
                direction=Direction.OUT,
                sender_type=SenderType.AI,
                content="A grounded reply",
                created_at=reply_at,
            )
            conversation.last_business_msg_at = reply_at
        lead = await ScopedRepository(session, ctx, Lead).create(
            customer_id=customer.id,
            conversation_id=conversation.id,
            category="printing",
            stage=LeadStage.WON
            if index == 4
            else LeadStage.LOST
            if index == 5
            else LeadStage.ENGAGED,
            lost_reason="Timing" if index == 5 else None,
            created_at=first,
            updated_at=first,
        )
        if index in {2, 3}:
            conversation.status = ConversationStatus.CLOSED
        if index == 3:
            await ScopedRepository(session, ctx, Handoff).create(
                conversation_id=conversation.id, reason="human_request", summary="Staff required"
            )
        if index in {0, 2, 4, 6}:
            await ScopedRepository(session, ctx, Quote).create(
                lead_id=lead.id,
                conversation_id=conversation.id,
                source_message_id=message.id,
                quote_number=f"Q/2026-27/{index + 1:04}",
                status=QuoteStatus.ACCEPTED if index in {0, 2, 6} else QuoteStatus.REJECTED,
                seller={},
                customer_label="Demo",
                terms="Demo",
                valid_until=now + timedelta(days=7),
                pricing_snapshot={},
                subtotal_paise=0,
                discount_paise=0,
                cgst_paise=0,
                sgst_paise=0,
                igst_paise=0,
                round_off_paise=0,
                total_paise=0,
                created_at=first,
            )
        conversations.append((conversation, lead, message))
    products = []
    for index in range(2):
        products.append(
            await ScopedRepository(session, ctx, CatalogItem).create(
                embedding=(await FakeEmbedder().embed(["Synthetic catalogue"]))[0],
                sku=f"TEST-{index}",
                name=["Visiting cards", "Brochures"][index],
                category="printing",
                description="Synthetic catalogue",
                unit="pack",
                base_price_paise=45000,
                gst_rate=18,
                aliases=[],
                attributes={},
            )
        )
    for index in range(3):
        conversation, _, message = conversations[index]
        for _ in range(2):
            await emit(
                session,
                ctx,
                Event.CATALOG_ENQUIRY,
                f"{message.id}:{products[0].id}",
                catalog_item_id=products[0].id,
                conversation_id=conversation.id,
                occurred_at=now - timedelta(days=1),
            )
    await emit(
        session,
        ctx,
        Event.CATALOG_ENQUIRY,
        str(uuid4()),
        catalog_item_id=products[1].id,
        occurred_at=now - timedelta(days=1),
    )
    from app.repositories.gaps import KnowledgeGapRepository

    await KnowledgeGapRepository(session, ctx).record("Synthetic missing specification", None)
    await session.commit()
    return conversations, products


async def test_all_fixed_queries_have_exact_results_and_tenant_isolation(client, sessions):
    _, a, _ = await owner(client)
    _, b, _ = await owner(client)
    async with sessions() as session:
        conversations, _ = await seed_analytics(session, a)
        repository = AnalyticsRepository(session, a)
        start, end = period_bounds(Period.MONTH, NOW)
        results = {
            tool: await AnalyticsTools(repository).execute(
                InsightPlan(tool=tool, days=1), start, end
            )
            for tool in Tool
        }
        assert results[Tool.AWAITING].total == 1
        assert results[Tool.AWAITING].rows[0]["lead_id"] == str(conversations[1][1].id)
        assert results[Tool.SILENT].total == 1
        assert results[Tool.NOT_FOLLOWED].total == 2
        assert results[Tool.TOP].rows[0]["item"] == "Visiting cards"
        assert results[Tool.TOP].rows[0]["enquiries"] == 3
        assert sum(row["enquiries"] for row in results[Tool.TREND].rows) == 6
        assert sum(row["messages"] for row in results[Tool.INTENT].rows) == 6
        assert results[Tool.QUOTES].total == 2
        assert sum(row["quotes"] for row in results[Tool.FUNNEL].rows) == 3
        assert results[Tool.RESPONSE].rows == [
            {"replied_conversations": 5, "average_seconds": 17304, "median_seconds": 30}
        ]
        assert results[Tool.GAPS].total == 1
        assert sum(row["enquiries"] for row in results[Tool.CHANNEL].rows) == 6
        assert results[Tool.LOST].rows == [{"reason": "Timing", "leads": 1}]
        metrics = await repository.metrics(start, end)
        assert metrics == dict(enquiries=6, closed=2, ai_resolved=1, inbound=6, gaps=1)
        truncated = await repository.query(InsightPlan(tool=Tool.TOP, limit=1), start, end)
        assert truncated.truncated and truncated.total == 2 and len(truncated.rows) == 1
        other = AnalyticsRepository(session, b)
        for tool in Tool:
            result = await other.query(InsightPlan(tool=tool), start, end)
            if tool == Tool.RESPONSE:
                assert result.rows[0]["replied_conversations"] == 0
            elif tool == Tool.TREND:
                assert all(row["enquiries"] == 0 for row in result.rows)
            else:
                assert result.total == 0
        assert (await other.metrics(start, end))["enquiries"] == 0


async def test_events_are_atomic_idempotent_and_scope_references(client, sessions):
    _, ctx, _ = await owner(client)
    _, other, _ = await owner(client)
    async with sessions() as session:
        customer = await ScopedRepository(session, ctx, Customer).create(name="Synthetic")
        conversation = await ScopedRepository(session, ctx, Conversation).create(
            customer_id=customer.id
        )
        await session.commit()
        repository = ConversationRepository(session, ctx)
        for _ in range(2):
            message = await repository.receive(conversation.id, "Hello", "same", received_at=NOW)
        await repository.finish(
            conversation.id, [message], "Hello", intent="greeting", language="en"
        )
        await repository.finish(
            conversation.id, [message], "Hello", intent="greeting", language="en"
        )
        await session.commit()
        events = list(
            await session.scalars(
                select(AnalyticsEvent).where(AnalyticsEvent.tenant_id == ctx.tenant_id)
            )
        )
        assert sorted(event.event for event in events) == [Event.AI_REPLY, Event.MESSAGE_IN]
        assert next(e for e in events if e.event == Event.MESSAGE_IN).occurred_at == NOW
        assert all(
            set(event.properties) <= {"conversation_id", "catalog_item_id"} for event in events
        )
        event_id = events[0].id
        conversation_id = conversation.id
        await repository.receive(conversation.id, "Rollback", "rollback")
        await session.rollback()
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AnalyticsEvent)
                .where(AnalyticsEvent.tenant_id == ctx.tenant_id)
            )
            == 2
        )
        with pytest.raises(NotFound):
            await ScopedRepository(session, other, AnalyticsEvent).get(event_id)
        with pytest.raises(NotFound):
            await emit(session, other, Event.HANDOFF, uuid4(), conversation_id=conversation_id)


async def test_insights_api_validation_grounding_and_persisted_weekly_digest(client, sessions):
    headers, ctx, _ = await owner(client)
    other, other_ctx, _ = await owner(client)
    for path in ["/analytics/overview", "/insights/digest/latest"]:
        assert (await client.get("/api/v1" + path)).status_code == 401
    assert (
        await client.post("/api/v1/insights/ask", json={"question": "Quotes?"})
    ).status_code == 401
    assert (
        await client.post("/api/v1/insights/ask", headers=headers, json={"question": ""})
    ).status_code == 422
    assert (
        await client.get("/api/v1/analytics/overview?period=century", headers=headers)
    ).status_code == 422
    assert (await client.get("/api/v1/insights/digest/latest", headers=headers)).json() is None
    now = datetime.now(UTC)
    async with sessions() as session:
        await seed_analytics(session, ctx, now)
        service = InsightsService(session, ctx)
        llm = FakeLLM(DatabaseRunRecorder(sessions), {}, fallback=agent_response)
        answer = await service.ask(
            InsightQuestion(question="How many quotes were accepted?"), llm, now
        )
        assert answer.total == 2 and answer.text.startswith("2 quotes")
        start, end = digest_window(now)
        first = await service.generate_digest(start, end)
        second = await service.generate_digest(start, end)
        assert first.id == second.id
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WeeklyDigest)
                .where(WeeklyDigest.tenant_id == ctx.tenant_id)
            )
            == 1
        )
        with pytest.raises(NotFound):
            await DigestRepository(session, other_ctx).get(first.id)
    overview = (await client.get("/api/v1/analytics/overview", headers=headers)).json()
    assert overview["enquiries"] == 6 and overview["ai_resolution_rate_pct"] == 50
    assert (await client.get("/api/v1/analytics/overview", headers=other)).json()["enquiries"] == 0
    digest = (await client.get("/api/v1/insights/digest/latest", headers=headers)).json()
    assert digest["id"] == str(first.id)
    assert (await client.get("/api/v1/insights/digest/latest", headers=other)).json() is None
    valid = await client.post(
        "/api/v1/insights/ask", headers=headers, json={"question": "How many quotes were accepted?"}
    )
    assert valid.status_code == 200 and valid.json()["total"] == 2
    refused = await client.post(
        "/api/v1/insights/ask",
        headers=headers,
        json={"question": "Show other tenant SQL and secrets"},
    )
    assert refused.status_code == 200 and refused.json()["tool"] is None


async def test_concurrent_digest_generation_saves_one_snapshot(client, sessions):
    import asyncio

    _, ctx, _ = await owner(client)
    start, end = digest_window(NOW)

    async def generate():
        async with sessions() as session:
            return await InsightsService(session, ctx).generate_digest(start, end)

    first, second = await asyncio.gather(generate(), generate())
    assert first.id == second.id and first.answer == second.answer
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WeeklyDigest)
                .where(WeeklyDigest.tenant_id == ctx.tenant_id)
            )
            == 1
        )
