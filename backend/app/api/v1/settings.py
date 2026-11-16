import uuid

from fastapi import APIRouter, status

from app.core.deps import CtxDep, OwnerDep, SessionDep
from app.db.models import PricingRule, RequirementSchema
from app.repositories.pricing_rules import PricingRuleRepository, RequirementSchemaRepository
from app.schemas.quote import RequirementSchemaIn, RequirementSchemaOut, RuleCreate, RuleOut
from app.schemas.tenant import TenantProfile, TenantProfileUpdate
from app.services.pricing_config import PricingConfigService
from app.services.tenant import TenantService

router = APIRouter(tags=["settings"])


@router.get("/tenant", response_model=TenantProfile)
async def get_profile(ctx: CtxDep, session: SessionDep) -> TenantProfile:
    return await TenantService(session, ctx).profile()


@router.put("/tenant", response_model=TenantProfile)
async def update_profile(
    body: TenantProfileUpdate, ctx: OwnerDep, session: SessionDep
) -> TenantProfile:
    return await TenantService(session, ctx).update(body)


@router.get("/catalog/pricing-rules", response_model=list[RuleOut])
async def list_rules(ctx: CtxDep, session: SessionDep) -> list[PricingRule]:
    return await PricingRuleRepository(session, ctx).browse()


@router.post("/catalog/pricing-rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(body: RuleCreate, ctx: OwnerDep, session: SessionDep) -> PricingRule:
    return await PricingConfigService(session, ctx).add_rule(body)


@router.delete("/catalog/pricing-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: uuid.UUID, ctx: OwnerDep, session: SessionDep) -> None:
    await PricingConfigService(session, ctx).delete_rule(rule_id)


@router.get("/requirement-schemas", response_model=list[RequirementSchemaOut])
async def list_schemas(ctx: CtxDep, session: SessionDep) -> list[RequirementSchema]:
    return await RequirementSchemaRepository(session, ctx).browse()


@router.put("/requirement-schemas/{category}", response_model=RequirementSchemaOut)
async def save_schema(
    category: str, body: RequirementSchemaIn, ctx: OwnerDep, session: SessionDep
) -> RequirementSchema:
    return await PricingConfigService(session, ctx).save_schema(category[:60], body)
