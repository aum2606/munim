from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound
from app.core.tenant import TenantContext
from app.db.models.knowledge import DocumentStatus, SourceType
from app.ingestion.chunker import TextChunk
from app.llm import Embedder
from app.repositories.catalog import CatalogRepository
from app.repositories.demo_seed import DemoSeedRepository
from app.repositories.documents import DocumentRepository
from app.schemas.catalog import CatalogInput


@dataclass(frozen=True)
class DemoBusiness:
    slug: str
    name: str
    business_type: str
    email: str
    catalog: tuple[CatalogInput, ...]
    faqs: tuple[tuple[str, str], ...]


def demo_businesses() -> tuple[DemoBusiness, ...]:
    def product(
        sku: str, name: str, paise: int, unit: str, aliases: list[str], category: str
    ) -> CatalogInput:
        from app.db.models.knowledge import StockStatus

        attributes: dict[str, str] = {}
        packs = {"CARD-100": "100", "FLYER-500": "500", "BRO-100": "100"}
        if sku in packs:
            attributes = {
                "pack_size": packs[sku],
                "default_size": "standard",
                "default_material": "standard",
                "default_sides": "single-sided",
                "default_colour": "colour",
                "default_finishing": "none",
            }
        if sku in {"PHOTO-DAY", "VIDEO-DAY"}:
            attributes = {
                "default_hours": "8",
                "default_crew_size": "2",
                "default_event_type": "wedding",
                "default_deliverables": "photo+video|photos and video"
                if sku == "VIDEO-DAY"
                else "photos|photo",
            }
        return CatalogInput(
            attributes=attributes,
            hsn_sac="998383" if sku in {"PHOTO-DAY", "VIDEO-DAY"} else "",
            sku=sku,
            name=name,
            base_price_paise=paise,
            unit=unit,
            aliases=aliases,
            category=category,
            stock_status=StockStatus.IN_STOCK,
        )

    return (
        DemoBusiness(
            "electronics",
            "Demo Electronics",
            "electronics",
            "electronics@example.com",
            (
                product(
                    "LAP-HP", "HP laptop", 4500000, "piece", ["laptop", "hp laptop"], "computers"
                ),
                product("SPK-BT", "Bluetooth speaker", 249900, "piece", ["speaker"], "audio"),
                product("USB-C", "USB-C cable", 39900, "piece", ["cable"], "accessories"),
                product("CHG-USB", "USB charger", 69900, "piece", ["charger"], "accessories"),
            ),
            (
                (
                    "What is your warranty policy?",
                    (
                        "Manufacturer warranty applies to eligible products. Keep your invoice; "
                        "the team confirms model-specific details."
                    ),
                ),
                (
                    "Do you offer local delivery?",
                    (
                        "Local delivery is available. The team confirms the address and "
                        "delivery arrangements before dispatch."
                    ),
                ),
                (
                    "When is your shop open?",
                    "Our shop is open Monday to Saturday, 10:00 to 19:00 IST. Sunday is closed.",
                ),
            ),
        ),
        DemoBusiness(
            "photography",
            "Demo Wedding Studio",
            "photography",
            "photography@example.com",
            (
                product(
                    "PHOTO-DAY",
                    "Wedding photography",
                    2500000,
                    "day",
                    ["wedding photography", "photography"],
                    "wedding",
                ),
                product(
                    "VIDEO-DAY",
                    "Wedding photo and video",
                    4500000,
                    "day",
                    ["photo video", "wedding video"],
                    "wedding",
                ),
                product("ALBUM", "Premium wedding album", 600000, "album", ["album"], "albums"),
                product(
                    "PREWED",
                    "Pre-wedding session",
                    1200000,
                    "session",
                    ["pre wedding"],
                    "portraits",
                ),
            ),
            (
                (
                    "What deliverables do you provide?",
                    (
                        "Edited photographs are delivered in a private online gallery. Albums "
                        "and video depend on the selected catalogue service."
                    ),
                ),
                (
                    "Do you travel for events?",
                    (
                        "Outstation events are considered. The team confirms travel "
                        "arrangements and availability before booking."
                    ),
                ),
                (
                    "How is booking confirmed?",
                    (
                        "The team checks the event date, venue and requirements, then confirms "
                        "the booking in writing."
                    ),
                ),
            ),
        ),
        DemoBusiness(
            "printing",
            "Demo Printing Press",
            "printing",
            "printing@example.com",
            (
                product(
                    "CARD-100",
                    "Visiting cards",
                    45000,
                    "pack of 100",
                    ["business cards", "visiting card"],
                    "cards",
                ),
                product(
                    "FLYER-500", "Flyers", 120000, "pack of 500", ["flyer", "leaflets"], "flyers"
                ),
                product("BRO-100", "Brochures", 350000, "pack of 100", ["brochure"], "brochures"),
                product(
                    "FLEX-SQFT",
                    "Flex printing",
                    5000,
                    "square foot",
                    ["flex", "banner printing"],
                    "banners",
                ),
            ),
            (
                (
                    "What is your delivery policy?",
                    (
                        "Local delivery is available after artwork approval. The team confirms "
                        "delivery details."
                    ),
                ),
                (
                    "What artwork formats do you accept?",
                    (
                        "We accept print-ready PDF files. Please include bleed and confirm "
                        "artwork before printing."
                    ),
                ),
                (
                    "When is your shop open?",
                    "Our shop is open Monday to Saturday, 10:00 to 19:00 IST. Sunday is closed.",
                ),
                (
                    "How long does printing take?",
                    (
                        "Standard orders take three working days after artwork approval. The "
                        "team confirms urgent orders."
                    ),
                ),
                (
                    "Can you print both sides?",
                    (
                        "Single-sided and double-sided options are available. The team confirms "
                        "the final specification."
                    ),
                ),
            ),
        ),
    )


async def seed_demo(
    sessions: async_sessionmaker[AsyncSession], embedder: Embedder, password_hash: str
) -> dict[str, TenantContext]:
    tenants = {}
    for business in demo_businesses():
        ctx = TenantContext(uuid5(NAMESPACE_URL, "urn:munim:demo:" + business.slug))
        async with sessions() as session:
            await DemoSeedRepository(session, ctx).ensure(
                business.name, business.business_type, business.email, password_hash
            )
            vectors = await embedder.embed(
                [catalog.name + " " + " ".join(catalog.aliases) for catalog in business.catalog]
            )
            for catalog, vector in zip(business.catalog, vectors, strict=True):
                await CatalogRepository(session, ctx).upsert(catalog, vector)
            from app.repositories.pricing_rules import PricingRuleRepository
            from app.repositories.requirements import RequirementRepository
            from app.schemas.pricing import PricingRuleInput

            await RequirementRepository(session, ctx).ensure_defaults()
            rules = PricingRuleRepository(session, ctx)
            if business.slug == "printing":
                card = await CatalogRepository(session, ctx).by_sku("CARD-100")
                assert card is not None
                existing = await rules.applicable(card)
                if not any(
                    rule.rule_type == "addon"
                    and rule.option == "sides"
                    and rule.value == "double-sided"
                    for rule in existing
                ):
                    await rules.add(
                        PricingRuleInput.model_validate(
                            {
                                "catalog_item_id": str(card.id),
                                "rule": {
                                    "rule_type": "addon",
                                    "option": "sides",
                                    "value": "double-sided",
                                    "amount_paise": 10000,
                                    "per_unit": True,
                                },
                            }
                        )
                    )
            documents = DocumentRepository(session, ctx)
            for question, answer in business.faqs:
                document_id = uuid5(ctx.tenant_id, "faq:" + question)
                try:
                    document = await documents.get(document_id)
                except NotFound:
                    document = await documents.create(
                        id=document_id,
                        title=question,
                        source_type=SourceType.FAQ,
                        storage_path="",
                        status=DocumentStatus.PENDING,
                    )
                text = question + "\n\n" + answer
                vector = (await embedder.embed([text]))[0]
                await documents.replace_chunks(
                    document.id, [TextChunk(text, 1, question, len(text.split()))], [vector]
                )
            await session.commit()
        tenants[business.slug] = ctx
    return tenants
