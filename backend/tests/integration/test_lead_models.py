from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.core.errors import NotFound
from app.db.models import Followup, Handoff, LeadEvent, ReplyDraft
from app.repositories.leads import LeadRepository
from app.repositories.scoped import ScopedRepository
from tests.integration.test_workspace import owner


async def test_lifecycle_resources_are_tenant_isolated(client, sessions):
    a, ctx_a, _ = await owner(client)
    _, ctx_b, _ = await owner(client)
    widget = (await client.post("/api/v1/playground/session", headers=a)).json()
    conversation_id = UUID(widget["conversation_id"])
    async with sessions() as session:
        from app.repositories.conversations import ConversationRepository

        message = await ConversationRepository(session, ctx_a).receive(
            conversation_id, "Hello", "test"
        )
        lead = await LeadRepository(session, ctx_a).for_conversation(conversation_id, "printing")
        assert lead.score == 0 and lead.estimated_value_paise == 0 and not lead.stage_override
        now = datetime.now(UTC)
        resources = [
            (LeadEvent, dict(lead_id=lead.id, event_type="stage", actor="ai", note="created")),
            (
                Followup,
                dict(
                    lead_id=lead.id,
                    scheduled_at=now,
                    source_at=now,
                    kind="no_reply",
                    draft_text="Can we help?",
                ),
            ),
            (
                Handoff,
                dict(conversation_id=conversation_id, reason="complaint", summary="Needs help"),
            ),
            (
                ReplyDraft,
                dict(
                    conversation_id=conversation_id,
                    source_message_id=message.id,
                    content="We can help.",
                ),
            ),
        ]
        for model, values in resources:
            resource = await ScopedRepository(session, ctx_a, model).create(**values)
            with pytest.raises(NotFound):
                await ScopedRepository(session, ctx_b, model).get(resource.id, for_update=True)
            assert await ScopedRepository(session, ctx_b, model).list() == []
        with pytest.raises(NotFound):
            await LeadRepository(session, ctx_b).get(lead.id)
        await session.commit()
