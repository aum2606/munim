from uuid import UUID, uuid4

import pytest

from app.core.errors import DomainError, NotFound
from app.llm import FakeLLM
from app.llm.offline import agent_response
from app.orchestrator.requirements import RequirementsFlow
from app.repositories.conversations import ConversationRepository
from app.repositories.leads import LeadRepository
from tests.integration.test_workspace import owner
from tests.unit.test_agents import MemoryRecorder


async def test_requirement_flow_persists_defaults_corrections_and_isolates_leads(client, sessions):
    a, ctx_a, _ = await owner(client)
    _, ctx_b, _ = await owner(client)
    started = (await client.post("/api/v1/playground/session", headers=a)).json()
    conversation_id = UUID(started["conversation_id"])
    fake = FakeLLM(MemoryRecorder(), {}, fallback=agent_response)
    async with sessions() as session:
        conversations = ConversationRepository(session, ctx_a)
        message = await conversations.receive(conversation_id, "quote", str(uuid4()))
        flow = RequirementsFlow(session, ctx_a, fake)
        state, text = await flow.collect(
            conversation_id,
            message.id,
            "item=visiting cards; quantity=500; sides=double-sided",
            "printing",
        )
        assert state["filled"]["quantity"] == 500 and text.count("?") == 2
        assert "How many" not in text
        state, text = await flow.collect(
            conversation_id,
            message.id,
            (
                "size=unknown; material=unknown; colour=unknown; finishing=unknown; "
                "deadline=2026-12-20"
            ),
            "printing",
        )
        assert state["ready_for_quote"] and state["missing"] == []
        assert state["filled"]["size"] == "standard"
        state, _ = await flow.collect(conversation_id, message.id, "quantity=1000", "printing")
        assert state["filled"]["quantity"] == 1000
        lead = await LeadRepository(session, ctx_a).for_conversation(conversation_id, "printing")
        assert lead.requirements == state["filled"] and lead.stage == "qualified"
        lead_id = lead.id
        await session.commit()
    async with sessions() as session:
        assert (await ConversationRepository(session, ctx_a).get(conversation_id)).active_flow[
            "filled"
        ]["quantity"] == 1000
        with pytest.raises(NotFound):
            await LeadRepository(session, ctx_b).get(lead_id)
        with pytest.raises(NotFound):
            await LeadRepository(session, ctx_b).for_conversation(conversation_id, "printing")
        assert await LeadRepository(session, ctx_b).list() == []
    async with sessions() as session:
        with pytest.raises(DomainError):
            await RequirementsFlow(session, ctx_a, fake).collect(
                conversation_id, message.id, "quantity=-2", "printing"
            )
