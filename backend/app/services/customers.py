"""A customer's right of access and erasure (India's DPDP Act 2023)."""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import NotFoundError
from app.ingestion.uploads import delete_upload
from app.repositories.customers import CustomerRepository
from app.repositories.quotes import QuoteRepository
from app.schemas.customers import (
    CustomerExport,
    CustomerOut,
    ExportedConversation,
    ExportedMessage,
    ExportedQuote,
    ExportedQuoteLine,
)

log = structlog.get_logger()


class CustomerService:
    def __init__(self, session: AsyncSession, ctx: TenantContext, settings: Settings) -> None:
        self._ctx = ctx
        self._settings = settings
        self._customers = CustomerRepository(session, ctx)
        self._quotes = QuoteRepository(session, ctx)

    async def export(self, customer_id: uuid.UUID) -> CustomerExport:
        customer = await self._customers.get(customer_id)
        if customer is None:
            raise NotFoundError("Customer not found")
        conversations = await self._customers.conversations(customer_id)
        messages = await self._customers.messages([c.id for c in conversations])
        exported_quotes = []
        for quote in await self._customers.quotes(customer_id):
            items = await self._quotes.items(quote.id)
            exported_quotes.append(
                ExportedQuote(
                    quote_number=quote.quote_number,
                    status=quote.status,
                    total_paise=quote.total_paise,
                    created_at=quote.created_at,
                    items=[
                        ExportedQuoteLine(
                            description=i.description,
                            qty=str(i.qty),
                            unit_price_paise=i.unit_price_paise,
                            line_total_paise=i.line_total_paise,
                        )
                        for i in items
                    ],
                )
            )
        return CustomerExport(
            customer=CustomerOut.model_validate(customer),
            conversations=[
                ExportedConversation(
                    id=c.id,
                    channel=c.channel,
                    created_at=c.created_at,
                    messages=[
                        ExportedMessage.model_validate(m, from_attributes=True)
                        for m in messages
                        if m.conversation_id == c.id
                    ],
                )
                for c in conversations
            ],
            quotes=exported_quotes,
        )

    async def erase(self, customer_id: uuid.UUID) -> None:
        if await self._customers.get(customer_id) is None:
            raise NotFoundError("Customer not found")
        erased = await self._customers.erase(customer_id)
        for path in erased.pdf_paths:
            delete_upload(self._settings.storage_dir, path)
        # Counts only: the log must not become a second copy of what was just deleted.
        log.info(
            "customer_erased",
            tenant_id=str(self._ctx.tenant_id),
            conversations=erased.conversations,
            messages=erased.messages,
            quotes=erased.quotes,
        )
