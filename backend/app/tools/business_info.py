from typing import Any

from pydantic import BaseModel

from app.repositories.tenant import TenantRepository


class BusinessInfo(BaseModel):
    name: str
    business_type: str
    timezone: str
    business_hours: dict[str, Any]


async def get_business_info(repo: TenantRepository) -> BusinessInfo:
    tenant = await repo.get()
    if tenant is None:
        raise LookupError("tenant not found")
    settings = await repo.get_settings()
    return BusinessInfo(
        name=tenant.name,
        business_type=tenant.business_type,
        timezone=tenant.timezone,
        business_hours=settings.business_hours if settings else {},
    )
