from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.errors import NotFound
from app.core.tenant import TenantContext
from app.db.models import (
    CatalogImport,
    CatalogItem,
    Chunk,
    Conversation,
    Customer,
    Document,
    KnowledgeGap,
    Message,
    PricingRule,
    WidgetSession,
)
from app.db.models.conversation import Direction, SenderType
from app.db.models.knowledge import RuleType, SourceType
from app.llm import FakeEmbedder
from app.repositories.identity import IdentityRepository
from app.repositories.scoped import ScopedRepository


async def test_every_phase1_resource_is_tenant_scoped(sessions) -> None:
    async with sessions() as session:
        identity = IdentityRepository(session)
        a = await identity.register("A", "printing", f"{uuid4()}@example.com", "A", "unused")
        b = await identity.register("B", "printing", f"{uuid4()}@example.com", "B", "unused")
        await session.commit()
        ctx_a, ctx_b = TenantContext(a.tenant_id), TenantContext(b.tenant_id)
        vector = (await FakeEmbedder().embed(["visiting card"]))[0]
        document = await ScopedRepository(session, ctx_b, Document).create(
            title="Private", source_type=SourceType.TXT, storage_path="private.txt"
        )
        catalog = await ScopedRepository(session, ctx_b, CatalogItem).create(
            sku="PRIVATE", name="Private", base_price_paise=45000, embedding=vector
        )
        customer = await ScopedRepository(session, ctx_b, Customer).create()
        conversation = await ScopedRepository(session, ctx_b, Conversation).create(
            customer_id=customer.id
        )
        message = await ScopedRepository(session, ctx_b, Message).create(
            conversation_id=conversation.id,
            direction=Direction.IN,
            sender_type=SenderType.CUSTOMER,
            content="private",
        )
        chunk = await ScopedRepository(session, ctx_b, Chunk).create(
            document_id=document.id, content="private", embedding=vector, token_count=1
        )
        rule = await ScopedRepository(session, ctx_b, PricingRule).create(
            catalog_item_id=catalog.id, rule_type=RuleType.MIN_ORDER, params={"quantity": 1}
        )
        imported = await ScopedRepository(session, ctx_b, CatalogImport).create(
            headers=["sku"], rows=[], mapping={}
        )
        widget = await ScopedRepository(session, ctx_b, WidgetSession).create(
            conversation_id=conversation.id,
            token_hash=uuid4().hex,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        gap = await ScopedRepository(session, ctx_b, KnowledgeGap).create(
            question="private", example_message_id=message.id
        )
        await session.commit()
        for resource in [
            document,
            catalog,
            customer,
            conversation,
            message,
            chunk,
            rule,
            imported,
            widget,
            gap,
        ]:
            repo_a = ScopedRepository(session, ctx_a, type(resource))
            repo_b = ScopedRepository(session, ctx_b, type(resource))
            assert await repo_a.list() == []
            with pytest.raises(NotFound):
                await repo_a.get(resource.id)
            with pytest.raises(NotFound):
                await repo_a.delete(resource.id)
            assert (await repo_b.get(resource.id)).tenant_id == ctx_b.tenant_id
        # Database constraints also reject cross-tenant parent references on write.
        with pytest.raises(IntegrityError):
            await ScopedRepository(session, ctx_a, Chunk).create(
                document_id=document.id, content="bad", embedding=vector, token_count=1
            )
        await session.rollback()
