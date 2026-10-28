from fastapi import APIRouter

from app.core.deps import Owner, Session
from app.repositories.onboarding import OnboardingRepository
from app.schemas.onboarding import OnboardingPreferences, OnboardingState

router = APIRouter(prefix="/onboarding")


@router.get("", response_model=OnboardingState)
async def state(session: Session, ctx: Owner) -> OnboardingState:
    return await OnboardingRepository(session, ctx).state()


@router.put("/preferences", response_model=OnboardingState)
async def preferences(body: OnboardingPreferences, session: Session, ctx: Owner) -> OnboardingState:
    return await OnboardingRepository(session, ctx).preferences(body)


@router.post("/complete", response_model=OnboardingState)
async def complete(session: Session, ctx: Owner) -> OnboardingState:
    return await OnboardingRepository(session, ctx).complete()
