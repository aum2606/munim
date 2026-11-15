from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import DocumentStatus, StockStatus
from app.db.session import SessionMaker
from app.jobs.handlers import build_handlers
from app.llm.embedder import FakeEmbedder
from app.llm.fake import FakeLLM
from app.repositories.catalog import CatalogRepository, CatalogRow
from app.repositories.documents import DocumentRepository
from app.services.documents import DocumentService
from app.tools.catalog_lookup import lookup_catalog
from app.tools.search import search_knowledge
from tests.conftest import make_tenant

MAXD = 0.65


class CrossScriptEmbedder(FakeEmbedder):
    """Pretends a Hindi phrase means the visiting-card item, like a multilingual model would."""

    def _one(self, text: str) -> list[float]:
        if text == "विज़िटिंग कार्ड":
            return super()._one(CARD_TEXT)
        return super()._one(text)


EMBEDDER = FakeEmbedder()
CARD = CatalogRow(
    sku="VC-100",
    name="Visiting card (100 pcs)",
    base_price_paise=25000,
    aliases=["Business Card", "name card"],
    category="Printing",
    description="Matt finish 300 gsm",
    unit="per 100",
)
CARD_TEXT = "Visiting card (100 pcs) business card name card Printing Matt finish 300 gsm"
FLEX = CatalogRow(sku="FLEX-1", name="Flex banner", base_price_paise=1800, unit="per sq ft")


@pytest.fixture
def storage(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={"storage_dir": str(tmp_path)})


async def _seed(sessionmaker: SessionMaker, ctx: TenantContext, *rows: CatalogRow) -> None:
    async with sessionmaker() as session:
        await CatalogRepository(session, ctx).upsert_many(list(rows))
        await session.commit()


async def _embed_catalog(
    sessionmaker: SessionMaker, ctx: TenantContext, settings: Settings
) -> None:
    handlers = build_handlers(EMBEDDER, settings, FakeLLM([]))
    await handlers["embed_catalog_items"](sessionmaker, ctx, {})


async def test_upsert_creates_then_updates_and_resets_the_embedding(
    sessionmaker: SessionMaker, storage: Settings
) -> None:
    ctx = await make_tenant(sessionmaker)
    async with sessionmaker() as session:
        assert await CatalogRepository(session, ctx).upsert_many([CARD, FLEX]) == (2, 0)
        await session.commit()
    await _embed_catalog(sessionmaker, ctx, storage)
    async with sessionmaker() as session:
        repo = CatalogRepository(session, ctx)
        assert await repo.without_embedding(10) == []
        changed = CatalogRow(
            sku="FLEX-1", name="Flex banner", base_price_paise=2000, unit="per sq ft"
        )
        assert await repo.upsert_many([changed]) == (0, 1)
        await session.commit()
        item = await repo.by_sku("flex-1")
        assert item is not None and item.base_price_paise == 2000
        assert [i.sku for i in await repo.without_embedding(10)] == ["FLEX-1"]  # needs re-embedding


async def test_catalog_is_tenant_isolated(sessionmaker: SessionMaker) -> None:
    a, b = await make_tenant(sessionmaker), await make_tenant(sessionmaker)
    await _seed(sessionmaker, a, CARD)
    async with sessionmaker() as session:
        mine, theirs = CatalogRepository(session, a), CatalogRepository(session, b)
        item = await mine.by_sku("VC-100")
        assert item is not None
        assert await theirs.get(item.id) is None
        assert await theirs.by_sku("VC-100") is None
        assert await theirs.browse() == []
        assert await theirs.by_ids([item.id]) == []
        assert await theirs.by_text("'visiting'", 5) == []
        assert await theirs.by_trigram("visiting card", 5) == []
        assert await theirs.by_alias("business card") == []
        (vector,) = await EMBEDDER.embed(["x"])
        assert await theirs.by_vector(vector, 5, 2.0) == []


async def test_lookup_strategies(sessionmaker: SessionMaker, storage: Settings) -> None:
    ctx = await make_tenant(sessionmaker)
    await _seed(sessionmaker, ctx, CARD, FLEX)
    await _embed_catalog(sessionmaker, ctx, storage)
    async with sessionmaker() as session:
        repo = CatalogRepository(session, ctx)
        by_sku = await lookup_catalog(repo, EMBEDDER, ["vc-100"], MAXD)
        assert [(h.sku, h.match) for h in by_sku] == [("VC-100", "sku")]
        by_alias = await lookup_catalog(repo, EMBEDDER, ["Business  Card"], MAXD)
        assert [(h.sku, h.match) for h in by_alias] == [("VC-100", "alias")]
        fuzzy = await lookup_catalog(repo, EMBEDDER, ["visting card"], MAXD)  # typo
        assert [(h.sku, h.match) for h in fuzzy][:1] == [("VC-100", "fuzzy")]
        assert fuzzy[0].base_price_paise == 25000 and fuzzy[0].stock_status == StockStatus.NA
        # no name match in any script, and nothing related: an honest empty result
        assert await lookup_catalog(repo, EMBEDDER, ["zzzz qqqq"], MAXD) == []
        # a Hindi phrase no text strategy can match is still found by meaning (vector search)
        hindi = await lookup_catalog(repo, CrossScriptEmbedder(), ["विज़िटिंग कार्ड"], MAXD)
        assert [(h.sku, h.match) for h in hindi] == [("VC-100", "search")]
        assert await lookup_catalog(repo, EMBEDDER, ["", "  "], MAXD) == []


async def test_inactive_items_are_never_found(sessionmaker: SessionMaker) -> None:
    ctx = await make_tenant(sessionmaker)
    await _seed(sessionmaker, ctx, CARD)
    async with sessionmaker() as session:
        repo = CatalogRepository(session, ctx)
        item = await repo.by_sku("VC-100")
        assert item is not None
        item.is_active = False
        await session.commit()
        assert await repo.by_sku("VC-100") is None
        assert await lookup_catalog(repo, EMBEDDER, ["VC-100"], MAXD) == [] or all(
            h.sku != "VC-100" for h in await lookup_catalog(repo, EMBEDDER, ["VC-100"], MAXD)
        )


async def test_faq_becomes_searchable_once_embedded(
    sessionmaker: SessionMaker, storage: Settings
) -> None:
    ctx = await make_tenant(sessionmaker)
    other = await make_tenant(sessionmaker)
    handlers = build_handlers(EMBEDDER, storage, FakeLLM([]))
    async with sessionmaker() as session:
        faq = await DocumentService(session, ctx, storage).create_faq(
            "What is your return policy?", "Returns accepted within 7 days."
        )
        await session.commit()
    async with sessionmaker() as session:  # pending documents are not searchable yet
        assert (
            await search_knowledge(
                DocumentRepository(session, ctx), EMBEDDER, "return policy", MAXD
            )
            == []
        )
    await handlers["embed_document"](sessionmaker, ctx, {"document_id": str(faq.id)})

    async with sessionmaker() as session:
        hits = await search_knowledge(
            DocumentRepository(session, ctx), EMBEDDER, "return policy", MAXD
        )
        assert [h.title for h in hits] == ["What is your return policy?"]
        assert "7 days" in hits[0].content
        # another tenant sees nothing, however it asks
        assert (
            await search_knowledge(
                DocumentRepository(session, other), EMBEDDER, "return policy", MAXD
            )
            == []
        )


async def test_text_upload_is_ingested_chunked_and_embedded(
    sessionmaker: SessionMaker, storage: Settings
) -> None:
    ctx = await make_tenant(sessionmaker)
    handlers = build_handlers(EMBEDDER, storage, FakeLLM([]))
    async with sessionmaker() as session:
        document = await DocumentService(session, ctx, storage).upload(
            None,
            "policies.txt",
            b"# Delivery\n\nFree delivery above 500 rupees.\n\n# Hours\n\nOpen 10 to 7.",
        )
        await session.commit()
    await handlers["ingest_document"](sessionmaker, ctx, {"document_id": str(document.id)})
    async with sessionmaker() as session:
        repo = DocumentRepository(session, ctx)
        stored = await repo.get(document.id)
        assert stored is not None and stored.status == DocumentStatus.READY
        assert len(await repo.chunk_texts(document.id)) == 2
        assert await repo.chunks_without_embedding(document.id) == []


async def test_unreadable_upload_is_marked_failed_with_a_reason(
    sessionmaker: SessionMaker, storage: Settings
) -> None:
    ctx = await make_tenant(sessionmaker)
    handlers = build_handlers(EMBEDDER, storage, FakeLLM([]))
    async with sessionmaker() as session:
        document = await DocumentService(session, ctx, storage).upload(
            None, "blank.txt", b"   \n  "
        )
        await session.commit()
    await handlers["ingest_document"](sessionmaker, ctx, {"document_id": str(document.id)})
    async with sessionmaker() as session:
        stored = await DocumentRepository(session, ctx).get(document.id)
        assert stored is not None
        assert stored.status == DocumentStatus.FAILED and "no text" in (stored.error or "")
