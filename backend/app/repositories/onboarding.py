from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models import CatalogItem, Document, Message, WidgetSession
from app.db.models.knowledge import DocumentStatus
from app.repositories.identity import TenantRepository
from app.schemas.onboarding import OnboardingPreferences, OnboardingState
from app.schemas.requirements import Category


class OnboardingRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def state(self) -> OnboardingState:
        tenant_repo = TenantRepository(self.session, self.ctx)
        tenant, settings = await tenant_repo.get(), await tenant_repo.settings()
        catalog_ready = bool(
            await self.session.scalar(
                select(CatalogItem.id)
                .where(CatalogItem.tenant_id == self.ctx.tenant_id, CatalogItem.is_active.is_(True))
                .limit(1)
            )
        )
        taxable = bool(
            await self.session.scalar(
                select(CatalogItem.id)
                .where(
                    CatalogItem.tenant_id == self.ctx.tenant_id,
                    CatalogItem.is_active.is_(True),
                    CatalogItem.gst_rate > 0,
                )
                .limit(1)
            )
        )
        knowledge_ready = bool(
            await self.session.scalar(
                select(Document.id)
                .where(
                    Document.tenant_id == self.ctx.tenant_id,
                    Document.status == DocumentStatus.READY,
                )
                .limit(1)
            )
        )
        tested = bool(
            await self.session.scalar(
                select(Message.id)
                .join(
                    WidgetSession,
                    (WidgetSession.conversation_id == Message.conversation_id)
                    & (WidgetSession.tenant_id == self.ctx.tenant_id),
                )
                .where(
                    Message.tenant_id == self.ctx.tenant_id,
                    Message.direction == "out",
                    Message.sender_type == "ai",
                    WidgetSession.is_playground.is_(True),
                    Message.attachments[0]["citations"] != [],
                )
                .limit(1)
            )
        )
        category = cast(
            Category,
            tenant.business_type
            if tenant.business_type
            in {"printing", "photography", "interior", "repair", "electronics"}
            else "printing",
        )
        return OnboardingState(
            profile_ready=bool(
                tenant.name and tenant.address and tenant.phone and tenant.state_code
            ),
            catalog_ready=catalog_ready,
            knowledge_ready=knowledge_ready,
            tax_profile_ready=not taxable or bool(tenant.gstin and tenant.state_code),
            playground_tested=tested,
            completed=settings.onboarding_completed_at is not None,
            preferences=OnboardingPreferences.model_validate(
                {
                    "category": category,
                    "tone": "formal" if settings.tone == "formal" else "friendly",
                    "languages": settings.languages,
                    "business_hours": settings.business_hours,
                }
            ),
        )

    async def preferences(self, body: OnboardingPreferences) -> OnboardingState:
        repository = TenantRepository(self.session, self.ctx)
        tenant, settings = await repository.get(), await repository.settings()
        tenant.business_type = body.category
        settings.tone, settings.languages = body.tone, list(body.languages)
        settings.business_hours = {day: list(window) for day, window in body.business_hours.items()}
        await self.session.commit()
        return await self.state()

    async def complete(self) -> OnboardingState:
        state = await self.state()
        if not all(
            (
                state.profile_ready,
                state.catalog_ready,
                state.knowledge_ready,
                state.tax_profile_ready,
                state.playground_tested,
            )
        ):
            raise DomainError(
                "Complete profile, catalogue, knowledge, tax details "
                "and a grounded playground test",
                409,
            )
        settings = await TenantRepository(self.session, self.ctx).settings()
        settings.onboarding_completed_at = settings.onboarding_completed_at or datetime.now(UTC)
        await self.session.commit()
        return await self.state()
