from typing import Any
from uuid import UUID

from fastapi import APIRouter, UploadFile
from pydantic import BaseModel

from app.core.deps import Config, Context, Owner, Session
from app.pricing.inr import format_inr
from app.quotes.settings import QuoteSettingsService
from app.repositories.identity import TenantRepository
from app.schemas.quote_profile import QuoteProfile
from app.schemas.quotes import QuoteSettings


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


@router.get("/tenant/quote-profile", response_model=QuoteProfile)
async def quote_profile(session: Session, ctx: Context) -> QuoteProfile:
    return QuoteProfile.model_validate(await TenantRepository(session, ctx).get())


@router.put("/tenant/quote-profile", response_model=QuoteProfile)
async def update_profile(
    body: QuoteProfile, session: Session, ctx: Owner, config: Config
) -> QuoteProfile:
    result = await QuoteSettingsService(session, ctx, config).profile(body)
    await session.commit()
    return result


@router.get("/tenant/settings")
async def quote_settings(session: Session, ctx: Context) -> dict[str, Any]:
    result = QuoteSettings.model_validate(await TenantRepository(session, ctx).settings())
    return {
        **result.model_dump(),
        "display_auto_send_limit": format_inr(result.auto_send_limit_paise),
    }


@router.put("/tenant/settings", response_model=QuoteSettings)
async def update_quote_settings(
    body: QuoteSettings, session: Session, ctx: Owner, config: Config
) -> QuoteSettings:
    result = await QuoteSettingsService(session, ctx, config).update(body)
    await session.commit()
    return result


@router.post("/tenant/logo", status_code=201)
async def logo(file: UploadFile, session: Session, ctx: Owner, config: Config) -> dict[str, str]:
    await QuoteSettingsService(session, ctx, config).logo(await file.read(2 * 1024 * 1024 + 1))
    await session.commit()
    return {"status": "saved"}
