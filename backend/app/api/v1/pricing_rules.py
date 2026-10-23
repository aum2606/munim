from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response

from app.core.deps import Context, Owner, Session
from app.repositories.pricing_rules import PricingRuleRepository
from app.schemas.pricing import PricingRuleInput

router = APIRouter(prefix="/catalog/pricing-rules")


@router.get("")
async def rules(session: Session, ctx: Context) -> list[dict[str, Any]]:
    return [
        {
            "id": rule.id,
            "catalog_item_id": rule.catalog_item_id,
            "category": rule.category,
            "rule": {"rule_type": rule.rule_type, **rule.params},
            "priority": rule.priority,
            "active_from": rule.active_from,
            "active_to": rule.active_to,
        }
        for rule in await PricingRuleRepository(session, ctx).list()
    ]


@router.post("", status_code=201)
async def create_rule(body: PricingRuleInput, session: Session, ctx: Owner) -> dict[str, UUID]:
    rule = await PricingRuleRepository(session, ctx).add(body)
    await session.commit()
    return {"id": rule.id}


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: UUID, session: Session, ctx: Owner) -> Response:
    await PricingRuleRepository(session, ctx).delete(rule_id)
    await session.commit()
    return Response(status_code=204)
