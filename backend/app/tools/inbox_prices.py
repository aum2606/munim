from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.tenant import TenantContext
from app.pricing.catalog import catalog_price
from app.quotes.pdf import quote_allowed_prices
from app.quotes.service import QuoteService
from app.repositories.catalog import CatalogRepository
from app.repositories.leads import LeadRepository


async def reply_prices(
    session: AsyncSession, ctx: TenantContext, config: Settings, conversation_id: UUID
) -> set[int]:
    # Explicit current-turn tool evidence. Staff text never authorizes its own amounts.
    prices = {
        catalog_price(product).paise
        for product in await CatalogRepository(session, ctx).list()
        if product.is_active
    }
    quote = await LeadRepository(session, ctx).latest_quote(conversation_id)
    if quote and quote.sent_at:
        prices |= quote_allowed_prices(await QuoteService(session, ctx, config).view(quote.id))
    return prices
