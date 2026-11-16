"""Owner-managed pricing rules and requirement schemas."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import FileRejectedError, NotFoundError
from app.db.models import PricingRule, RequirementSchema
from app.orchestrator.requirements import validate_slots
from app.repositories.catalog import CatalogRepository
from app.repositories.pricing_rules import PricingRuleRepository, RequirementSchemaRepository
from app.schemas.quote import RequirementSchemaIn, RuleCreate


class PricingConfigService:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._catalog = CatalogRepository(session, ctx)
        self._rules = PricingRuleRepository(session, ctx)
        self._schemas = RequirementSchemaRepository(session, ctx)

    async def add_rule(self, data: RuleCreate) -> PricingRule:
        if (
            data.catalog_item_id is not None
            and await self._catalog.get(data.catalog_item_id) is None
        ):
            raise NotFoundError("Item not found")  # also what another tenant's item looks like
        return await self._rules.add(
            rule_type=data.rule_type,
            params=data.params(),
            catalog_item_id=data.catalog_item_id,
            category=data.category,
        )

    async def delete_rule(self, rule_id: uuid.UUID) -> None:
        if not await self._rules.delete(rule_id):
            raise NotFoundError("Rule not found")

    async def save_schema(self, category: str, data: RequirementSchemaIn) -> RequirementSchema:
        valid_defaults = validate_slots(data.json_schema, data.defaults)
        if set(valid_defaults) != set(data.defaults):
            raise FileRejectedError("Each default must be a valid value for its own detail")
        if any(slot not in data.json_schema["properties"] for slot in data.question_hints):
            raise FileRejectedError("question_hints names a detail that is not in the schema")
        return await self._schemas.upsert(
            category,
            data.json_schema,
            valid_defaults,
            {k: v[:300] for k, v in data.question_hints.items()},
        )
