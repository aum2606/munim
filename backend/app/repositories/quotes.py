from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models.quote import Quote, QuoteItem, QuoteSequence, QuoteStatus
from app.repositories.scoped import ScopedRepository


class QuoteRepository(ScopedRepository[Quote]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, Quote)

    async def by_status(self, status: QuoteStatus | None) -> list[Quote]:
        statement = select(Quote).where(Quote.tenant_id == self.ctx.tenant_id)
        if status:
            statement = statement.where(Quote.status == status)
        return list(
            await self.session.scalars(statement.order_by(Quote.created_at.desc()).limit(100))
        )

    async def for_message(self, message_id: UUID) -> Quote | None:
        return (
            await self.session.scalars(
                select(Quote).where(
                    Quote.tenant_id == self.ctx.tenant_id,
                    Quote.source_message_id == message_id,
                )
            )
        ).one_or_none()

    async def lines(self, quote_id: UUID) -> list[QuoteItem]:
        await self.get(quote_id)
        return list(
            await self.session.scalars(
                select(QuoteItem)
                .where(
                    QuoteItem.tenant_id == self.ctx.tenant_id,
                    QuoteItem.quote_id == quote_id,
                )
                .order_by(QuoteItem.position)
            )
        )

    async def replace_lines(self, quote_id: UUID, lines: list[dict[str, Any]]) -> None:
        await self.get(quote_id)
        await self.session.execute(
            delete(QuoteItem).where(
                QuoteItem.tenant_id == self.ctx.tenant_id, QuoteItem.quote_id == quote_id
            )
        )
        for index, values in enumerate(lines):
            self.session.add(
                QuoteItem(tenant_id=self.ctx.tenant_id, quote_id=quote_id, position=index, **values)
            )
        await self.session.flush()


class QuoteSequenceRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def next_for_year(self, financial_year: str) -> int:
        statement = insert(QuoteSequence).values(
            tenant_id=self.ctx.tenant_id, financial_year=financial_year, last_value=1
        )
        return (
            await self.session.scalars(
                statement.on_conflict_do_update(
                    index_elements=[QuoteSequence.tenant_id, QuoteSequence.financial_year],
                    set_={"last_value": QuoteSequence.last_value + 1},
                ).returning(QuoteSequence.last_value)
            )
        ).one()
