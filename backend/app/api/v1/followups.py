import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import CtxDep, SessionDep, SettingsDep
from app.db.models import FollowUpStatus
from app.schemas.followups import FollowUpOut, FollowUpSend
from app.services.followups import FollowUpService

router = APIRouter(tags=["follow-ups"])


@router.get("/follow-ups", response_model=list[FollowUpOut])
async def list_follow_ups(
    ctx: CtxDep,
    session: SessionDep,
    settings: SettingsDep,
    state: Annotated[FollowUpStatus | None, Query(alias="status")] = None,
) -> list[FollowUpOut]:
    return await FollowUpService(session, ctx, settings).listing(state)


@router.post("/follow-ups/{follow_up_id}/send", status_code=status.HTTP_204_NO_CONTENT)
async def send_follow_up(
    follow_up_id: uuid.UUID,
    body: FollowUpSend,
    ctx: CtxDep,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    await FollowUpService(session, ctx, settings).send(follow_up_id, body.text)


@router.post("/follow-ups/{follow_up_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_follow_up(
    follow_up_id: uuid.UUID, ctx: CtxDep, session: SessionDep, settings: SettingsDep
) -> None:
    await FollowUpService(session, ctx, settings).dismiss(follow_up_id)
