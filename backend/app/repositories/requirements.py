from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models.requirements import RequirementSchema
from app.repositories.scoped import ScopedRepository
from app.schemas.requirements import RequirementDefinition
from seeds.requirements import requirement_defaults


class RequirementRepository(ScopedRepository[RequirementSchema]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, RequirementSchema)

    async def ensure_defaults(self) -> None:
        for definition in requirement_defaults():
            await self.session.execute(
                insert(RequirementSchema)
                .values(tenant_id=self.ctx.tenant_id, **definition.model_dump())
                .on_conflict_do_nothing(index_elements=["tenant_id", "category"])
            )

    async def for_category(self, category: str) -> RequirementSchema:
        await self.ensure_defaults()
        return (
            await self.session.scalars(
                select(RequirementSchema).where(
                    RequirementSchema.tenant_id == self.ctx.tenant_id,
                    RequirementSchema.category == category,
                )
            )
        ).one()

    async def save(self, definition: RequirementDefinition) -> RequirementSchema:
        schema = await self.for_category(definition.category)
        schema.json_schema = definition.json_schema
        schema.defaults = definition.defaults
        schema.question_templates = definition.question_templates
        await self.session.flush()
        return schema
