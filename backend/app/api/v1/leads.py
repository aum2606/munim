from uuid import UUID

from fastapi import APIRouter, Query

from app.core.deps import Context, Session
from app.db.models.lead import LeadStage
from app.repositories.leads import LeadRepository
from app.schemas.leads import EventView, LeadPatch, LeadView

router = APIRouter(prefix="/leads")


@router.get("", response_model=list[LeadView])
async def leads(
    session: Session,
    ctx: Context,
    stage: LeadStage | None = None,
    score_min: int = Query(default=0, ge=0, le=100),
    followup_due: bool = False,
) -> list[LeadView]:
    return [
        LeadView.model_validate(lead)
        for lead in await LeadRepository(session, ctx).filtered(stage, score_min, followup_due)
    ]


@router.get("/{lead_id}", response_model=LeadView)
async def lead(lead_id: UUID, session: Session, ctx: Context) -> LeadView:
    return LeadView.model_validate(await LeadRepository(session, ctx).get(lead_id))


@router.patch("/{lead_id}", response_model=LeadView)
async def patch(lead_id: UUID, body: LeadPatch, session: Session, ctx: Context) -> LeadView:
    lead = await LeadRepository(session, ctx).patch(lead_id, body)
    await session.commit()
    return LeadView.model_validate(lead)


@router.get("/{lead_id}/events", response_model=list[EventView])
async def events(lead_id: UUID, session: Session, ctx: Context) -> list[EventView]:
    return [
        EventView.model_validate(event)
        for event in await LeadRepository(session, ctx).events(lead_id)
    ]
