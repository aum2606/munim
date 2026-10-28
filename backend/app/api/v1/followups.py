from uuid import UUID

from fastapi import APIRouter

from app.core.deps import Config, Context, Owner, Session
from app.core.followups import FollowupService
from app.repositories.followups import FollowupRepository
from app.repositories.identity import TenantRepository
from app.schemas.leads import FollowupAction, FollowupPolicy, FollowupView

router = APIRouter()


@router.get("/followups", response_model=list[FollowupView])
async def followups(session: Session, ctx: Context) -> list[FollowupView]:
    return [
        FollowupView.model_validate(draft)
        for draft in await FollowupRepository(session, ctx).pending()
    ]


@router.post("/followups/{followup_id}/action", response_model=FollowupView)
async def action(
    followup_id: UUID, body: FollowupAction, session: Session, ctx: Owner, config: Config
) -> FollowupView:
    return FollowupView.model_validate(
        await FollowupService(session, ctx, config).act(
            followup_id, body.action == "approve", body.template_id
        )
    )


@router.get("/tenant/followup-policy", response_model=FollowupPolicy)
async def policy(session: Session, ctx: Context) -> FollowupPolicy:
    return FollowupPolicy.model_validate(
        (await TenantRepository(session, ctx).settings()).followup_policy
    )


@router.put("/tenant/followup-policy", response_model=FollowupPolicy)
async def save_policy(body: FollowupPolicy, session: Session, ctx: Owner) -> FollowupPolicy:
    settings = await TenantRepository(session, ctx).settings()
    settings.followup_policy = body.model_dump()
    await session.commit()
    return body
