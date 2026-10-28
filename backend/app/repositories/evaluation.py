import secrets
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.core.tenant import TenantContext
from app.db.models import CatalogItem
from app.llm import FakeEmbedder
from app.pricing.catalog import catalog_price
from app.repositories.identity import IdentityRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.knowledge import Fact
from app.schemas.requirements import Category


class EvaluationRepository:
    """Bootstrap a new synthetic workspace; never reuse or mutate a business's catalogue."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_workspace(self) -> tuple[TenantContext, dict[Category, Fact]]:
        user = await IdentityRepository(self.session).register(
            "Synthetic evaluation",
            "printing",
            f"eval-{uuid4()}@example.invalid",
            "Evaluation",
            hash_password(secrets.token_urlsafe(32)),
        )
        ctx = TenantContext(user.tenant_id, user.id, "owner")
        definitions: dict[Category, tuple[str, int]] = {
            "printing": ("Visiting cards", 45000),
            "photography": ("Wedding album", 600000),
            "interior": ("Design consultation", 150000),
            "repair": ("Device diagnosis", 50000),
            "electronics": ("USB cable", 25000),
        }
        facts = {}
        for category, (name, paise) in definitions.items():
            product = await ScopedRepository(self.session, ctx, CatalogItem).create(
                sku="EVAL-" + category,
                name=name,
                category=category,
                description="Contract fixture",
                unit="unit",
                base_price_paise=paise,
                gst_rate=18,
                embedding=(await FakeEmbedder().embed([name]))[0],
            )
            price = catalog_price(product)
            facts[category] = Fact(
                ref=f"catalog:{product.id}",
                kind="catalog",
                text=f"{name}: {price.formatted} per unit. GST 18%. Stock: in_stock.",
                price=price,
            )
        await self.session.commit()
        return ctx, facts
