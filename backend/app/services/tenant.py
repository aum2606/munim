from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import NotFoundError
from app.pricing.gst import state_code_of
from app.repositories.tenant import TenantRepository
from app.schemas.tenant import TenantProfile, TenantProfileUpdate

_TENANT_FIELDS = ("name", "business_type", "gstin", "state_code", "address", "phone")
_SETTINGS_FIELDS = ("quote_terms", "quote_validity_days")


class TenantService:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._repo = TenantRepository(session, ctx)

    async def profile(self) -> TenantProfile:
        tenant = await self._repo.get()
        settings = await self._repo.get_settings()
        if tenant is None or settings is None:
            raise NotFoundError("Business not found")
        return TenantProfile(
            id=tenant.id,
            name=tenant.name,
            business_type=tenant.business_type,
            gstin=tenant.gstin,
            state_code=tenant.state_code,
            address=tenant.address,
            phone=tenant.phone,
            quote_terms=settings.quote_terms,
            quote_validity_days=settings.quote_validity_days,
        )

    async def update(self, data: TenantProfileUpdate) -> TenantProfile:
        changes = data.model_dump(exclude_unset=True)
        if changes.get("gstin"):
            changes["state_code"] = state_code_of(changes["gstin"])  # the GSTIN decides the state
        for field in ("name", "business_type", "quote_validity_days"):
            if field in changes and changes[field] is None:
                del changes[field]  # these cannot be cleared
        await self._repo.update_profile(**{k: changes[k] for k in _TENANT_FIELDS if k in changes})
        settings = await self._repo.get_settings()
        if settings is not None:
            for field in _SETTINGS_FIELDS:
                if field in changes:
                    setattr(settings, field, changes[field])
        return await self.profile()
