from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Unauthorized
from app.core.tenant import TenantContext
from app.db.models import Conversation, Customer, Tenant, WidgetSession
from app.repositories.scoped import ScopedRepository
from app.schemas.privacy import NOTICE_VERSION


class WidgetCredentialRepository:
    """Public-key / hashed-token identity discovery, before a tenant is known."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def tenant(self, public_key: str) -> Tenant:
        tenant = (
            await self.session.scalars(select(Tenant).where(Tenant.widget_public_key == public_key))
        ).one_or_none()
        if tenant is None:
            raise Unauthorized()
        return tenant

    async def authenticate(self, token_hash: str) -> WidgetSession:
        widget = (
            await self.session.scalars(
                select(WidgetSession).where(
                    WidgetSession.token_hash == token_hash,
                    WidgetSession.expires_at > datetime.now(UTC),
                    or_(
                        WidgetSession.is_playground.is_(True),
                        and_(
                            WidgetSession.consented_at.is_not(None),
                            WidgetSession.notice_version == NOTICE_VERSION,
                        ),
                    ),
                )
            )
        ).one_or_none()
        if widget is None:
            raise Unauthorized()
        return widget


class WidgetRepository(ScopedRepository[WidgetSession]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, WidgetSession)

    async def create_session(
        self, token_hash: str, expires_at: datetime, *, public_consent: bool = False
    ) -> WidgetSession:
        customer = await ScopedRepository(self.session, self.ctx, Customer).create()
        conversation = await ScopedRepository(self.session, self.ctx, Conversation).create(
            customer_id=customer.id
        )
        return await self.create(
            conversation_id=conversation.id,
            token_hash=token_hash,
            expires_at=expires_at,
            is_playground=not public_consent,
            consented_at=datetime.now(UTC) if public_consent else None,
            notice_version=NOTICE_VERSION if public_consent else None,
        )
