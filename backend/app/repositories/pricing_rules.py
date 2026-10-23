from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models.knowledge import CatalogItem, PricingRule, RuleType
from app.repositories.catalog import CatalogRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.pricing import PricingRuleInput, Rule


class PricingRuleRepository(ScopedRepository[PricingRule]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, PricingRule)

    async def add(self, body: PricingRuleInput) -> PricingRule:
        if body.catalog_item_id:
            await CatalogRepository(self.session, self.ctx).get(body.catalog_item_id)
        values = body.model_dump(exclude={"rule"})
        return await self.create(
            **values,
            rule_type=RuleType(body.rule.rule_type),
            params=body.rule.model_dump(mode="json", exclude={"rule_type"}),
        )

    async def applicable(self, catalog: CatalogItem, now: datetime | None = None) -> list[Rule]:
        moment = now or datetime.now(UTC)
        rules = await self.session.scalars(
            select(PricingRule)
            .where(
                PricingRule.tenant_id == self.ctx.tenant_id,
                or_(
                    PricingRule.catalog_item_id.is_(None), PricingRule.catalog_item_id == catalog.id
                ),
                or_(PricingRule.category.is_(None), PricingRule.category == catalog.category),
                or_(PricingRule.active_from.is_(None), PricingRule.active_from <= moment),
                or_(PricingRule.active_to.is_(None), PricingRule.active_to >= moment),
            )
            .order_by(PricingRule.priority, PricingRule.created_at, PricingRule.id)
        )
        return [
            PricingRuleInput.model_validate(
                {"rule": {"rule_type": rule.rule_type.value, **rule.params}}
            ).rule
            for rule in rules
        ]
