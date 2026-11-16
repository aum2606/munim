import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import Channel, ChannelAccount


class ChannelAccountRepository:
    """A business's connected WhatsApp number. Tenant-scoped."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    async def get(self) -> ChannelAccount | None:
        return await self._session.scalar(
            select(ChannelAccount).where(
                ChannelAccount.tenant_id == self._ctx.tenant_id,
                ChannelAccount.channel == Channel.WHATSAPP,
            )
        )

    async def save(
        self, external_id: str, display_phone: str | None, credentials_encrypted: str
    ) -> ChannelAccount:
        account = await self.get()
        if account is None:
            account = ChannelAccount(tenant_id=self._ctx.tenant_id, channel=Channel.WHATSAPP)
            self._session.add(account)
        account.external_id = external_id
        account.display_phone = display_phone
        account.credentials_encrypted = credentials_encrypted
        account.is_active = True
        await self._session.flush()
        return account

    async def delete(self) -> None:
        account = await self.get()
        if account is not None:
            await self._session.delete(account)


async def tenant_for_phone_number_id(
    session: AsyncSession, phone_number_id: str
) -> uuid.UUID | None:
    """Webhook routing, deliberately not tenant-scoped: it is how we find out WHICH tenant an
    incoming message belongs to. Only active accounts receive messages."""
    return await session.scalar(
        select(ChannelAccount.tenant_id).where(
            ChannelAccount.channel == Channel.WHATSAPP,
            ChannelAccount.external_id == phone_number_id,
            ChannelAccount.is_active.is_(True),
        )
    )
