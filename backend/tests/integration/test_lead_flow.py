from datetime import UTC, datetime
from uuid import UUID

from app.core.leads import LeadService
from app.db.models.lead import LeadStage
from app.llm import FakeLLM
from app.llm.offline import agent_response
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.conversations import ConversationRepository
from app.repositories.leads import LeadRepository
from tests.integration.test_workspace import owner


async def test_lead_scoring_idempotency_manual_override_and_scoped_api(client, sessions):
    a, ctx, user = await owner(client)
    b, _, other = await owner(client)
    widget = (await client.post("/api/v1/playground/session", headers=a)).json()
    conversation_id = UUID(widget["conversation_id"])
    fake = FakeLLM(DatabaseRunRecorder(sessions), {}, fallback=agent_response)
    async with sessions() as session:
        repository = ConversationRepository(session, ctx)
        message = await repository.receive(conversation_id, "Hello", "first")
        message.processed_at = datetime.now(UTC)
        await session.commit()
        await LeadService(session, ctx, fake).update(message.id)
        lead = await LeadRepository(session, ctx).for_conversation(conversation_id, "printing")
        assert lead.stage == LeadStage.ENGAGED and lead.score == 20
        lead_id = lead.id
        await LeadService(session, ctx, fake).update(message.id)
        assert len(fake.calls) == 1
    path = "/api/v1/leads/" + str(lead_id)
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=b)).status_code == 404
    assert (await client.get(path + "/events", headers=b)).status_code == 404
    assert (await client.patch(path, headers=b, json={"stage": "won"})).status_code == 404
    assert (await client.patch(path, headers=a, json={"stage": "invalid"})).status_code == 422
    assert (
        await client.patch(path, headers=a, json={"assigned_to": str(other)})
    ).status_code == 404
    response = await client.patch(
        path,
        headers=a,
        json={"stage": "lost", "lost_reason": "No longer needed", "assigned_to": str(user)},
    )
    assert response.status_code == 200 and response.json()["stage_override"]
    async with sessions() as session:
        repository = ConversationRepository(session, ctx)
        message = await repository.receive(conversation_id, "New question", "second")
        message.processed_at = datetime.now(UTC)
        await session.commit()
        await LeadService(session, ctx, fake).update(message.id)
    assert (await client.get(path, headers=a)).json()["stage"] == "lost"
    events = (await client.get(path + "/events", headers=a)).json()
    assert any(event["actor"] == str(user) and event["to_value"] == "lost" for event in events)
    assert (await client.get("/api/v1/leads?stage=lost&score_min=1", headers=a)).json()[0][
        "id"
    ] == str(lead_id)
    assert (await client.get("/api/v1/leads?score_min=101", headers=a)).status_code == 422
