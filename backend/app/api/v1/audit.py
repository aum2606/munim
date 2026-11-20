from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import OwnerDep, SessionDep
from app.repositories.audit import AuditRepository
from app.schemas.audit import AuditEventOut

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[AuditEventOut])
async def list_audit_events(
    ctx: OwnerDep, session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[AuditEventOut]:
    return [
        AuditEventOut.model_validate(e, from_attributes=True)
        for e in await AuditRepository(session, ctx).browse(limit)
    ]
