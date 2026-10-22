from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.deps import Config, Context, Session
from app.repositories.identity import TenantRepository


class TenantView(BaseModel):
    id: UUID
    name: str
    business_type: str
    widget_public_key: str
    widget_script_url: str
    public_api_url: str
    model_mode: str


router = APIRouter()


@router.get("/tenant", response_model=TenantView)
async def tenant(ctx: Context, session: Session, config: Config) -> TenantView:
    business = await TenantRepository(session, ctx).get()
    return TenantView(
        id=business.id,
        name=business.name,
        business_type=business.business_type,
        widget_public_key=business.widget_public_key,
        widget_script_url=config.widget_script_url,
        public_api_url=config.public_api_url,
        model_mode=config.llm_provider,
    )
