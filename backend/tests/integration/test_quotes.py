import asyncio
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID, uuid4

from pypdf import PdfReader

from app.core.config import Settings
from app.core.security import issue_token
from app.llm import FakeEmbedder, FakeLLM
from app.llm.offline import agent_response
from app.orchestrator.requirements import RequirementsFlow
from app.pricing.quote_number import next_quote_number
from app.quotes.service import QuoteService
from app.repositories.conversations import ConversationRepository
from app.repositories.identity import UserRepository
from app.repositories.quotes import QuoteRepository, QuoteSequenceRepository
from seeds.demo import seed_demo
from tests.integration.test_workspace import owner
from tests.unit.test_agents import MemoryRecorder


async def test_quote_generation_pdf_snapshot_unknown_pricing_and_isolation(
    client, sessions, tmp_path
):
    tenants = await seed_demo(sessions, FakeEmbedder(), "synthetic-unused-hash")
    ctx = tenants["printing"]
    fake = FakeLLM(MemoryRecorder(), {}, fallback=agent_response)
    app = client._transport.app
    settings = Settings(database_url=app.state.settings.database_url, storage_dir=str(tmp_path))
    app.state.settings.storage_dir = str(tmp_path)
    a, other, _ = await owner(client)
    async with sessions() as session:
        user = (await UserRepository(session, ctx).list())[0]
        token, _ = issue_token(app.state.settings, user.id, ctx.tenant_id, "access")
    own_headers = {"Authorization": "Bearer " + token}
    widget = (await client.post("/api/v1/playground/session", headers=own_headers)).json()
    conversation_id = UUID(widget["conversation_id"])
    async with sessions() as session:
        repo = ConversationRepository(session, ctx)
        inbound = await repo.receive(conversation_id, "quote", str(uuid4()))
        state, _ = await RequirementsFlow(session, ctx, fake).collect(
            conversation_id,
            inbound.id,
            (
                "item=visiting cards; quantity=500; sides=double-sided; size=standard; "
                "material=standard; colour=colour; finishing=none; deadline=2026-12-20"
            ),
            "printing",
        )
        assert state["ready_for_quote"]
        service = QuoteService(session, ctx, settings)
        quote = await service.create_from_requirements(conversation_id, inbound.id, fake)
        assert (
            await service.create_from_requirements(conversation_id, inbound.id, fake)
        ).id == quote.id
        view = await service.view(quote.id)
        assert view.status == "pending_approval" and not any(
            line.needs_owner_pricing for line in view.lines
        )
        assert view.totals.subtotal_paise == 275000
        assert view.totals.cgst_paise == 24750 and view.totals.sgst_paise == 24750
        assert view.totals.total_paise == 324500
        pdf = await service.pdf(quote.id)
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        assert (
            "3,245.00" in text
            and "GSTIN" in text
            and "Three Thousand Two Hundred Forty Five" in text
        )
        quote_id = quote.id
        await session.commit()
    async with sessions() as session:
        import pytest

        from app.core.errors import NotFound

        with pytest.raises(NotFound):
            await QuoteRepository(session, other).lines(quote_id)
        assert await QuoteRepository(session, other).list() == []
    for path in (f"/api/v1/quotes/{quote_id}", f"/api/v1/quotes/{quote_id}/pdf"):
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers=a)).status_code == 404
        assert (await client.get(path, headers=own_headers)).status_code == 200
    assert (await client.get("/api/v1/quotes?status=invalid", headers=a)).status_code == 422
    async with sessions() as session:
        inbound = await ConversationRepository(session, ctx).receive(
            conversation_id, "different quote", str(uuid4())
        )
        conversation = await ConversationRepository(session, ctx).get(conversation_id)
        conversation.active_flow = {**state, "filled": {**state["filled"], "item": "spaceship"}}
        await session.flush()
        unpriced = await QuoteService(session, ctx, settings).create_from_requirements(
            conversation_id, inbound.id, fake
        )
        view = await QuoteService(session, ctx, settings).view(unpriced.id)
        assert any(line.needs_owner_pricing for line in view.lines)
        assert view.status == "pending_approval"


async def test_quote_sequences_are_atomic_scoped_and_reset_by_financial_year(client, sessions):
    _, a, _ = await owner(client)
    _, b, _ = await owner(client)

    async def reserve(ctx, when):
        async with sessions() as session:
            number = await next_quote_number(QuoteSequenceRepository(session, ctx), when)
            await session.commit()
            return number

    when = datetime(2026, 10, 23, tzinfo=UTC)
    numbers = await asyncio.gather(*(reserve(a, when) for _ in range(12)))
    assert len(set(numbers)) == 12 and "Q/2026-27/0012" in numbers
    assert await reserve(b, when) == "Q/2026-27/0001"
    assert await reserve(a, datetime(2027, 4, 1, tzinfo=UTC)) == "Q/2027-28/0001"
