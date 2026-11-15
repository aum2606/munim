"""Create the demo businesses: `python -m seeds.load` (or `make seed`).

Safe to run twice. Embeddings are filled in by the worker (so the worker must be running).
Passwords are random and printed once here: they are never stored in the repository.
"""

import asyncio
import secrets

from app.core.config import Settings, get_settings
from app.core.context import TenantContext
from app.core.security import hash_password
from app.db.session import SessionMaker, make_engine, make_sessionmaker
from app.jobs.queue import enqueue
from app.repositories.auth import AuthRepository
from app.repositories.catalog import CatalogRepository
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
        await CatalogRepository(session, ctx).upsert_many(business.items)
        await enqueue(session, ctx, "embed_catalog_items")
        documents = DocumentService(session, ctx, settings)
        for question, answer in business.faqs:
            await documents.create_faq(question, answer)  # also queues its embedding
        await session.commit()
        return ctx


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
