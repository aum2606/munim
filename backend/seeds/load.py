"""Create the demo businesses: `python -m seeds.load` (or `make seed`).

Safe to run twice. Embeddings are filled in by the worker (so the worker must be running).
Passwords are random and printed once here: they are never stored in the repository.
"""

import asyncio
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.context import TenantContext
from app.core.security import hash_password
from app.db.models import RuleType
from app.db.session import SessionMaker, make_engine, make_sessionmaker
from app.jobs.queue import enqueue
from app.pricing.gst import state_code_of
from app.repositories.auth import AuthRepository
from app.repositories.catalog import CatalogRepository
from app.repositories.pricing_rules import PricingRuleRepository, RequirementSchemaRepository
from app.repositories.tenant import TenantRepository
from app.services.documents import DocumentService
from seeds.data import BUSINESSES, DemoBusiness


async def load_business(
    sessionmaker: SessionMaker, business: DemoBusiness, password: str, settings: Settings
) -> TenantContext | None:
    """Returns the new tenant's context, or None if the demo owner already exists."""
    async with sessionmaker() as session:
        auth = AuthRepository(session)
        if await auth.get_user_by_email(business.owner_email):
            return None
        owner = await auth.create_tenant_with_owner(
            business_name=business.name,
            business_type=business.business_type,
            owner_name="Demo Owner",
            email=business.owner_email,
            password_hash=hash_password(password),
        )
        ctx = TenantContext(tenant_id=owner.tenant_id, user_id=owner.id)
        catalog = CatalogRepository(session, ctx)
        await catalog.upsert_many(business.items)
        await _configure_quotes(session, ctx, catalog, business)
        await enqueue(session, ctx, "embed_catalog_items")
        documents = DocumentService(session, ctx, settings)
        for question, answer in business.faqs:
            await documents.create_faq(question, answer)  # also queues its embedding
        await session.commit()
        return ctx


async def _configure_quotes(
    session: AsyncSession, ctx: TenantContext, catalog: CatalogRepository, business: DemoBusiness
) -> None:
    """Business profile (for the PDF), pricing rules and what to ask before quoting."""
    tenants = TenantRepository(session, ctx)
    await tenants.update_profile(
        gstin=business.gstin,
        state_code=state_code_of(business.gstin),
        address=business.address,
        phone=business.phone,
    )
    settings = await tenants.get_settings()
    if settings is not None:
        settings.quote_terms = business.quote_terms
    rules = PricingRuleRepository(session, ctx)
    for rule in business.rules:
        item = await catalog.by_sku(rule.sku)
        if item is not None:
            await rules.add(
                rule_type=RuleType(rule.rule_type),
                params=rule.params,
                catalog_item_id=item.id,
                category=None,
            )
    schemas = RequirementSchemaRepository(session, ctx)
    for seed in business.schemas:
        await schemas.upsert(seed.category, seed.json_schema, seed.defaults, seed.question_hints)


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    for business in BUSINESSES.values():
        password = secrets.token_urlsafe(12)
        if await load_business(sessionmaker, business, password, settings):
            print(f"{business.name}\n  login:    {business.owner_email}\n  password: {password}")
        else:
            print(f"{business.name}: already exists, skipped")
    await engine.dispose()
    print("Start the worker so the catalogue and FAQs get embedded for search.")


if __name__ == "__main__":
    asyncio.run(main())
