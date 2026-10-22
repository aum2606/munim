from uuid import uuid4

from app.core.tenant import TenantContext
from app.db.models import Chunk, Document
from app.db.models.knowledge import DocumentStatus, SourceType
from app.llm import FakeEmbedder
from app.repositories.catalog import CatalogRepository
from app.repositories.identity import IdentityRepository
from app.repositories.scoped import ScopedRepository
from app.repositories.search import SearchRepository, reciprocal_rank_fusion
from app.schemas.catalog import CatalogInput
from app.tools.catalog_lookup import CatalogLookup
from app.tools.search import KnowledgeSearch


async def test_hybrid_search_sku_alias_trigram_and_isolation(sessions):
    async with sessions() as session:
        identity = IdentityRepository(session)
        a = await identity.register("A", "printing", f"{uuid4()}@example.com", "A", "unused")
        b = await identity.register("B", "printing", f"{uuid4()}@example.com", "B", "unused")
        await session.commit()
        ctx_a, ctx_b = TenantContext(a.tenant_id), TenantContext(b.tenant_id)
        embedder = FakeEmbedder()
        vector = (await embedder.embed(["visiting cards"]))[0]
        catalog = await CatalogRepository(session, ctx_a).upsert(
            CatalogInput(
                sku="CARD-001",
                name="Visiting cards",
                aliases=["business cards"],
                base_price_paise=45000,
            ),
            vector,
        )
        document = await ScopedRepository(session, ctx_a, Document).create(
            title="Delivery",
            source_type=SourceType.TXT,
            storage_path="unused",
            status=DocumentStatus.READY,
        )
        chunk = await ScopedRepository(session, ctx_a, Chunk).create(
            document_id=document.id,
            content="Delivery takes three working days.",
            token_count=6,
            embedding=(await embedder.embed(["delivery"]))[0],
        )
        await ScopedRepository(session, ctx_a, Chunk).create(
            document_id=document.id, content="Special price INR 1", token_count=4, embedding=vector
        )
        await session.commit()
        lookup = CatalogLookup(SearchRepository(session, ctx_a), embedder)
        for query in [
            "CARD-001",
            "business cards",
            "visiting cards ka rate kya hai",
            "visting cards",
        ]:
            facts = (await lookup.lookup_catalog(query)).facts
            assert facts and facts[0].price.paise == 45000
            assert facts[0].ref == "catalog:" + str(catalog.id)
        assert (
            await CatalogLookup(SearchRepository(session, ctx_b), embedder).lookup_catalog(
                "visiting cards"
            )
        ).facts == []
        result = await KnowledgeSearch(SearchRepository(session, ctx_a), embedder).search_knowledge(
            "delivery"
        )
        assert result.facts[0].ref == "chunk:" + str(chunk.id)
        assert (
            await KnowledgeSearch(SearchRepository(session, ctx_b), embedder).search_knowledge(
                "delivery"
            )
        ).facts == []
        assert all(
            "INR" not in fact.text
            for fact in (
                await KnowledgeSearch(SearchRepository(session, ctx_a), embedder).search_knowledge(
                    "special price"
                )
            ).facts
        )
        catalog.is_active = False
        await session.commit()
        assert (await lookup.lookup_catalog("CARD-001")).facts == []


def test_rank_fusion_removes_duplicates_and_is_stable():
    a, b = uuid4(), uuid4()
    assert reciprocal_rank_fusion([[a, a, b], [b]], 2) == [b, a]
    assert reciprocal_rank_fusion([], 5) == []
