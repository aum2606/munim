"""Usage, cost and latency reports come from fixed queries and never cross tenants."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import update

from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import AgentRunStatus, Channel, Direction, Message, SenderType
from app.db.session import SessionMaker
from app.llm.base import ChatMessage
from app.llm.costs import estimate_cost_micros
from app.llm.fake import FakeLLM
from app.llm.recording import agent_run
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.chat import ChatRepository
from app.tools.metrics import usage_report
from tests.conftest import make_tenant

M120, M20 = "openai/gpt-oss-120b", "openai/gpt-oss-20b"


async def add_run(
    sm: SessionMaker,
    ctx: TenantContext,
    agent: str,
    model: str | None,
    *,
    ms: int,
    tokens_in: int = 2_000,
    tokens_out: int = 500,
    status: AgentRunStatus = AgentRunStatus.OK,
    message_id=None,  # noqa: ANN001
) -> None:
    async with sm() as session:
        await AgentRunRepository(session, ctx).add(
            agent=agent,
            prompt_version=f"{agent}@x",
            input={},
            status=status,
            model=model,
            latency_ms=ms,
            prompt_tokens=tokens_in,
            completion_tokens=tokens_out,
            cost_estimate_micros=estimate_cost_micros(model, tokens_in, tokens_out),
            message_id=message_id,
        )
        await session.commit()


async def test_every_recorded_run_carries_its_list_price_cost(sessionmaker: SessionMaker) -> None:
    ctx = await make_tenant(sessionmaker)
    llm = FakeLLM(['{"ok": true}'])
    async with agent_run(sessionmaker, ctx, agent="router", prompt_version="r@1", input={}) as run:
        run.result = await llm.complete("small", [ChatMessage(role="user", content="hi")])
        run.result = type(run.result)(
            run.result.text, "groq", M120, prompt_tokens=2_000, completion_tokens=500
        )
    async with sessionmaker() as session:
        (row,) = await AgentRunRepository(session, ctx).list_recent()
    assert row.cost_estimate_micros == 600


async def test_report_groups_by_agent_and_model_with_percentiles(
    sessionmaker: SessionMaker,
) -> None:
    ctx = await make_tenant(sessionmaker)
    for ms in (100, 200, 300, 400, 1000):
        await add_run(sessionmaker, ctx, "knowledge", M120, ms=ms)
    await add_run(sessionmaker, ctx, "router", M20, ms=50)
    await add_run(sessionmaker, ctx, "router", M20, ms=70, status=AgentRunStatus.ERROR)
    await add_run(sessionmaker, ctx, "router", "mystery-model", ms=10)  # no listed price

    async with sessionmaker() as session:
        report = await usage_report(session, ctx)

    by_key = {(r.agent, r.model): r for r in report.rows}
    knowledge = by_key[("knowledge", M120)]
    assert (knowledge.calls, knowledge.errors) == (5, 0)
    assert (knowledge.p50_ms, knowledge.p95_ms) == (300, 880)  # 95th percentile, interpolated
    assert knowledge.prompt_tokens == 10_000 and knowledge.cost_micros == 3_000
    router = by_key[("router", M20)]
    assert (router.calls, router.errors, router.cost_micros) == (2, 1, 600)
    assert report.cost_micros == 3_600
    assert report.unpriced_calls == 1  # the cost is understated by that many calls


async def test_cost_per_turn_and_first_response_time(sessionmaker: SessionMaker) -> None:
    ctx = await make_tenant(sessionmaker)
    async with sessionmaker() as session:
        chat = ChatRepository(session, ctx)
        conversation = await chat.start_conversation(Channel.PLAYGROUND)
        ids = []
        for gap_s in (2, 4):  # the AI answers 2 s and 4 s after the customer wrote
            inbound = await chat.add_message(
                conversation, direction=Direction.IN, sender_type=SenderType.CUSTOMER, content="q"
            )
            reply = await chat.add_message(
                conversation,
                direction=Direction.OUT,
                sender_type=SenderType.AI,
                content="a",
                reply_to_id=inbound.id,
            )
            start = datetime.now(UTC) - timedelta(minutes=5)
            await session.execute(
                update(Message).where(Message.id == inbound.id).values(created_at=start)
            )
            await session.execute(
                update(Message)
                .where(Message.id == reply.id)
                .values(created_at=start + timedelta(seconds=gap_s))
            )
            ids.append(inbound.id)
        await session.commit()
    for message_id in ids:  # two model calls per turn: 600 + 300 micro-dollars
        await add_run(sessionmaker, ctx, "knowledge", M120, ms=100, message_id=message_id)
        await add_run(sessionmaker, ctx, "router", M20, ms=100, message_id=message_id)

    async with sessionmaker() as session:
        report = await usage_report(session, ctx)
    assert report.turns == 2
    assert report.cost_per_turn_micros == 900
    assert (report.first_response_p50_ms, report.first_response_p95_ms) == (3000, 3900)


async def test_an_empty_tenant_reports_zeros_not_errors(sessionmaker: SessionMaker) -> None:
    ctx = await make_tenant(sessionmaker)
    async with sessionmaker() as session:
        report = await usage_report(session, ctx)
    assert (report.rows, report.turns, report.cost_micros, report.cost_per_turn_micros) == (
        [],
        0,
        0,
        0,
    )
    assert report.first_response_p50_ms is None and report.first_response_p95_ms is None


async def test_the_report_only_counts_the_since_window_and_one_tenant(
    sessionmaker: SessionMaker,
) -> None:
    mine, other = await make_tenant(sessionmaker), await make_tenant(sessionmaker)
    await add_run(sessionmaker, mine, "router", M20, ms=10)
    await add_run(sessionmaker, other, "router", M20, ms=10)
    await add_run(sessionmaker, other, "knowledge", M120, ms=10)
    async with sessionmaker() as session:
        assert (await usage_report(session, mine)).cost_micros == 300  # not other's 900
        future = datetime.now(UTC) + timedelta(hours=1)
        assert (await usage_report(session, mine, since=future)).rows == []


# --- the owner's overview --------------------------------------------------------------------


async def test_overview_counts_the_period_and_keeps_businesses_apart(
    client: httpx.AsyncClient, sessionmaker: SessionMaker, settings: Settings
) -> None:
    from app.services.quotes import QuoteService
    from tests.conftest import bearer, register
    from tests.integration.test_inbox import login, sent_quote

    ctx, _, quote_id, email = await sent_quote(sessionmaker, settings, days_ago=0.1)
    token = await login(client, email)
    _, stranger = await register(client)

    data = (await client.get("/api/v1/metrics/overview?days=7", headers=bearer(token))).json()
    assert data["days"] == 7 and data["customer_messages"] == 2 and data["ai_replies"] >= 1
    assert data["quotes_by_status"] == {"sent": 1}
    assert sum(data["leads_by_stage"].values()) == 1
    assert data["accepted_value_paise"] == 0 and data["open_knowledge_gaps"] == 0
    assert data["usage"], "the model calls of the conversation are listed"
    assert data["turns"] >= 1 and data["unpriced_calls"] >= 1  # the fake model has no list price

    async with sessionmaker() as session:  # the customer accepts: the value counts
        await QuoteService(session, ctx, settings).mark_accepted(quote_id)
        await session.commit()
    data = (await client.get("/api/v1/metrics/overview", headers=bearer(token))).json()
    assert data["quotes_by_status"] == {"accepted": 1} and data["accepted_value_paise"] == 165200

    nothing = (await client.get("/api/v1/metrics/overview", headers=bearer(stranger))).json()
    assert nothing["customer_messages"] == 0 and nothing["quotes_by_status"] == {}
    assert nothing["accepted_value_paise"] == 0 and nothing["usage"] == []


async def test_overview_is_owner_only_and_validates_the_window(
    client: httpx.AsyncClient,
) -> None:
    from tests.conftest import PASSWORD, bearer, register, unique_email

    _, owner = await register(client)
    assert (await client.get("/api/v1/metrics/overview")).status_code == 401
    for bad in ("0", "366", "abc"):
        assert (
            await client.get(f"/api/v1/metrics/overview?days={bad}", headers=bearer(owner))
        ).status_code == 422
    email = unique_email()
    await client.post(
        "/api/v1/users",
        json={"email": email, "name": "Staff", "password": PASSWORD, "role": "staff"},
        headers=bearer(owner),
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    staff = login.json()["access_token"]
    assert (await client.get("/api/v1/metrics/overview", headers=bearer(staff))).status_code == 403
