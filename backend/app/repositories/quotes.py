import uuid
from datetime import date

from sqlalchemy import ColumnElement, and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import Customer, Lead, Quote, QuoteItem, QuoteSequence, QuoteStatus
from app.pricing.engine import Totals
from app.pricing.quote_number import fiscal_year, format_quote_number


class QuoteRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    def _mine(self, *extra: ColumnElement[bool]) -> ColumnElement[bool]:
        return and_(Quote.tenant_id == self._ctx.tenant_id, *extra)

    async def next_number(self, issued_on: date) -> str:
        """Q/2026-27/0007: one counter per tenant per Indian financial year. The upsert takes a
        row lock, so two quotes created at once can never get the same number."""
        label = fiscal_year(issued_on)
        values = insert(QuoteSequence).values(
            id=uuid.uuid4(), tenant_id=self._ctx.tenant_id, fiscal_year=label, last_number=1
        )
        statement = values.on_conflict_do_update(
            index_elements=["tenant_id", "fiscal_year"],
            set_={"last_number": QuoteSequence.last_number + 1},
        ).returning(QuoteSequence.last_number)
        number = await self._session.scalar(statement)
        if number is None:
            raise LookupError("quote sequence not returned")
        return format_quote_number(label, number)

    async def add(
        self,
        *,
        lead_id: uuid.UUID,
        number: str,
        totals: Totals,
        valid_until: date,
        buyer_state_code: str | None,
    ) -> Quote:
        quote = Quote(
            tenant_id=self._ctx.tenant_id,
            lead_id=lead_id,
            quote_number=number,
            status=QuoteStatus.PENDING_APPROVAL,
            valid_until=valid_until,
            buyer_state_code=buyer_state_code,
            **self.total_columns(totals),
        )
        self._session.add(quote)
        await self._session.flush()
        return quote

    @staticmethod
    def total_columns(totals: Totals) -> dict[str, int]:
        return {
            "subtotal_paise": totals.subtotal_paise,
            "discount_paise": totals.discount_paise,
            "cgst_paise": totals.cgst_paise,
            "sgst_paise": totals.sgst_paise,
            "igst_paise": totals.igst_paise,
            "round_off_paise": totals.round_off_paise,
            "total_paise": totals.total_paise,
        }

    async def get(self, quote_id: uuid.UUID) -> Quote | None:
        return await self._session.scalar(select(Quote).where(self._mine(Quote.id == quote_id)))

    async def browse(self, status: QuoteStatus | None = None, limit: int = 100) -> list[Quote]:
        query = select(Quote).where(self._mine())
        if status:
            query = query.where(Quote.status == status)
        result = await self._session.scalars(query.order_by(Quote.created_at.desc()).limit(limit))
        return list(result)

    async def items(self, quote_id: uuid.UUID) -> list[QuoteItem]:
        result = await self._session.scalars(
            select(QuoteItem)
            .where(QuoteItem.tenant_id == self._ctx.tenant_id, QuoteItem.quote_id == quote_id)
            .order_by(QuoteItem.position)
        )
        return list(result)

    async def replace_items(self, quote_id: uuid.UUID, items: list[QuoteItem]) -> None:
        await self._session.execute(
            delete(QuoteItem).where(
                QuoteItem.tenant_id == self._ctx.tenant_id, QuoteItem.quote_id == quote_id
            )
        )
        self._session.add_all(items)
        await self._session.flush()

    async def for_lead(self, lead_id: uuid.UUID) -> list[Quote]:
        result = await self._session.scalars(
            select(Quote)
            .where(self._mine(Quote.lead_id == lead_id))
            .order_by(Quote.created_at.desc())
        )
        return list(result)

    async def summaries(
        self, status: QuoteStatus | None = None, limit: int = 100
    ) -> list[tuple[Quote, str | None, int]]:
        """Quotes with the customer's name and how many lines still need an owner price."""
        unpriced = (
            select(func.count())
            .select_from(QuoteItem)
            .where(QuoteItem.quote_id == Quote.id, QuoteItem.needs_owner_pricing.is_(True))
            .correlate(Quote)
            .scalar_subquery()
        )
        query = (
            select(Quote, Customer.name, unpriced)
            .join(Lead, Lead.id == Quote.lead_id)
            .join(Customer, Customer.id == Lead.customer_id)
            .where(self._mine())
        )
        if status:
            query = query.where(Quote.status == status)
        rows = await self._session.execute(query.order_by(Quote.created_at.desc()).limit(limit))
        return [(quote, name, int(count)) for quote, name, count in rows]

    async def customer_name(self, lead_id: uuid.UUID) -> str | None:
        return await self._session.scalar(
            select(Customer.name)
            .join(Lead, Lead.customer_id == Customer.id)
            .where(Lead.tenant_id == self._ctx.tenant_id, Lead.id == lead_id)
        )
