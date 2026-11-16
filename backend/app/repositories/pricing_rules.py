import uuid

from sqlalchemy import ColumnElement, and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import CatalogItem, PricingRule, RequirementSchema, RuleType


class PricingRuleRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    def _mine(self, *extra: ColumnElement[bool]) -> ColumnElement[bool]:
        return and_(PricingRule.tenant_id == self._ctx.tenant_id, *extra)

    async def browse(self) -> list[PricingRule]:
        result = await self._session.scalars(
            select(PricingRule).where(self._mine()).order_by(PricingRule.created_at)
        )
        return list(result)

    async def applying_to(self, item: CatalogItem) -> list[PricingRule]:
        """Active rules for this item, or for the whole category it belongs to."""
        target = [PricingRule.catalog_item_id == item.id]
        if item.category:
            target.append(PricingRule.category == item.category)
        result = await self._session.scalars(
            select(PricingRule).where(self._mine(PricingRule.is_active.is_(True), or_(*target)))
        )
        return list(result)

    async def add(
        self,
        *,
        rule_type: RuleType,
        params: dict[str, object],
        catalog_item_id: uuid.UUID | None,
        category: str | None,
    ) -> PricingRule:
        rule = PricingRule(
            tenant_id=self._ctx.tenant_id,
            rule_type=rule_type,
            params=params,
            catalog_item_id=catalog_item_id,
            category=category,
        )
        self._session.add(rule)
        await self._session.flush()
        return rule

    async def delete(self, rule_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            delete(PricingRule).where(self._mine(PricingRule.id == rule_id))
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]


class RequirementSchemaRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    async def browse(self) -> list[RequirementSchema]:
        result = await self._session.scalars(
            select(RequirementSchema)
            .where(RequirementSchema.tenant_id == self._ctx.tenant_id)
            .order_by(RequirementSchema.category)
        )
        return list(result)

    async def get(self, category: str) -> RequirementSchema | None:
        return await self._session.scalar(
            select(RequirementSchema).where(
                RequirementSchema.tenant_id == self._ctx.tenant_id,
                RequirementSchema.category == category,
            )
        )

    async def upsert(
        self,
        category: str,
        json_schema: dict[str, object],
        defaults: dict[str, object],
        question_hints: dict[str, str],
    ) -> RequirementSchema:
        schema = await self.get(category)
        if schema is None:
            schema = RequirementSchema(tenant_id=self._ctx.tenant_id, category=category)
            self._session.add(schema)
        schema.json_schema = json_schema
        schema.defaults = defaults
        schema.question_hints = question_hints
        await self._session.flush()
        return schema
