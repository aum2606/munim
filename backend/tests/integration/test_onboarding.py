from uuid import UUID, uuid4

from app.db.models import CatalogItem, Document
from app.db.models.knowledge import DocumentStatus, SourceType
from app.llm import FakeEmbedder
from app.repositories.conversations import ConversationRepository
from app.repositories.scoped import ScopedRepository
from tests.integration.test_workspace import owner


async def test_onboarding_requirements_preferences_and_isolation(client, sessions):
    auth, ctx, _ = await owner(client)
    other, _, _ = await owner(client)
    assert (await client.get("/api/v1/onboarding")).status_code == 401
    assert (await client.post("/api/v1/onboarding/complete", headers=auth)).status_code == 409
    preferences = {
        "category": "printing",
        "tone": "formal",
        "languages": ["en", "hinglish"],
        "business_hours": {"monday": ["10:00", "19:00"]},
    }
    saved = await client.put("/api/v1/onboarding/preferences", headers=auth, json=preferences)
    assert saved.status_code == 200, saved.text
    assert saved.json()["preferences"]["tone"] == "formal"
    invalid = {**preferences, "business_hours": {"monday": ["invalid", "19:00"]}}
    assert (
        await client.put("/api/v1/onboarding/preferences", headers=auth, json=invalid)
    ).status_code == 422
    profile = {
        "name": "Synthetic Printing",
        "phone": "+919000000001",
        "address": "Demo market",
        "state_code": "24",
        "gstin": "24AAAAA0000A1Z5",
    }
    assert (
        await client.put("/api/v1/tenant/quote-profile", headers=auth, json=profile)
    ).status_code == 200
    async with sessions() as session:
        catalog = await ScopedRepository(session, ctx, CatalogItem).create(
            sku="ONBOARD",
            name="Visiting cards",
            category="printing",
            description="Synthetic",
            unit="pack",
            base_price_paise=45000,
            gst_rate=18,
            embedding=(await FakeEmbedder().embed(["Visiting cards"]))[0],
        )
        await ScopedRepository(session, ctx, Document).create(
            title="Synthetic FAQ",
            source_type=SourceType.FAQ,
            storage_path="unused",
            status=DocumentStatus.READY,
        )
        await session.commit()
        catalog_id = catalog.id
    before = (await client.get("/api/v1/onboarding", headers=auth)).json()
    assert before["profile_ready"] and before["catalog_ready"] and before["knowledge_ready"]
    assert not before["playground_tested"]
    assert (await client.post("/api/v1/onboarding/complete", headers=auth)).status_code == 409
    widget = (await client.post("/api/v1/playground/session", headers=auth)).json()
    async with sessions() as session:
        conversation_id = UUID(widget["conversation_id"])
        repository = ConversationRepository(session, ctx)
        source = await repository.receive(conversation_id, "Visiting cards price", str(uuid4()))
        await repository.finish(
            conversation_id,
            [source],
            "Synthetic grounded answer",
            intent="pricing",
            language="en",
            citations=["catalog:" + str(catalog_id)],
        )
        await session.commit()
    finished = await client.post("/api/v1/onboarding/complete", headers=auth)
    assert finished.status_code == 200 and finished.json()["completed"]
    assert not (await client.get("/api/v1/onboarding", headers=other)).json()["completed"]
