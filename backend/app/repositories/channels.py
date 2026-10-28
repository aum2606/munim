from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFound
from app.core.tenant import TenantContext
from app.db.models import (
    ChannelAccount,
    ChannelDelivery,
    Conversation,
    Customer,
    Message,
    WhatsAppContact,
    WhatsAppTemplate,
)
from app.db.models.channel import AccountStatus, ChannelStatusReceipt, DeliveryStatus
from app.db.models.conversation import ConversationStatus, Direction
from app.repositories.scoped import ScopedRepository


class ChannelDiscovery:
    """Signed webhook identity discovery only; never returns credentials."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def tenant(self, external_id: str, waba_id: str) -> TenantContext | None:
        tenant_id = await self.session.scalar(
            select(ChannelAccount.tenant_id).where(
                ChannelAccount.type == "whatsapp",
                ChannelAccount.external_id == external_id,
                ChannelAccount.business_account_id == waba_id,
            )
        )
        return TenantContext(tenant_id) if tenant_id else None


class ChannelRepository(ScopedRepository[ChannelAccount]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, ChannelAccount)

    async def by_phone(self, external_id: str) -> ChannelAccount:
        account = (
            await self.session.scalars(
                select(ChannelAccount).where(
                    ChannelAccount.tenant_id == self.ctx.tenant_id,
                    ChannelAccount.type == "whatsapp",
                    ChannelAccount.external_id == external_id,
                )
            )
        ).one_or_none()
        if account is None:
            raise NotFound()
        return account

    async def contact(self, conversation_id: UUID) -> WhatsAppContact:
        contact = (
            await self.session.scalars(
                select(WhatsAppContact)
                .where(
                    WhatsAppContact.tenant_id == self.ctx.tenant_id,
                    WhatsAppContact.conversation_id == conversation_id,
                )
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if contact is None:
            raise NotFound()
        return contact

    async def inbound(
        self,
        account: ChannelAccount,
        wa_id: str,
        external_id: str,
        text: str,
        timestamp: datetime,
        kind: str,
        attachments: list[dict[str, str]],
    ) -> Message:
        # A per-tenant/account/contact advisory lock serializes creation without FK-lock deadlocks.
        lock = int.from_bytes(
            sha256(f"{self.ctx.tenant_id}:{account.id}:{wa_id}".encode()).digest()[:8], signed=True
        )
        await self.session.execute(select(func.pg_advisory_xact_lock(lock)))
        key = "wa:" + str(account.id) + ":" + sha256(external_id.encode()).hexdigest()
        existing = (
            await self.session.scalars(
                select(Message).where(
                    Message.tenant_id == self.ctx.tenant_id,
                    Message.external_id == key,
                )
            )
        ).one_or_none()
        if existing is not None:
            return existing  # replay never reopens a conversation or resets the 24-hour window
        contact = (
            await self.session.scalars(
                select(WhatsAppContact).where(
                    WhatsAppContact.tenant_id == self.ctx.tenant_id,
                    WhatsAppContact.account_id == account.id,
                    WhatsAppContact.wa_id == wa_id,
                )
            )
        ).one_or_none()
        if contact is None:
            customer = await ScopedRepository(self.session, self.ctx, Customer).create(
                phone="+" + wa_id
            )
            conversation = await ScopedRepository(self.session, self.ctx, Conversation).create(
                customer_id=customer.id, channel="whatsapp"
            )
            contact = await ScopedRepository(self.session, self.ctx, WhatsAppContact).create(
                account_id=account.id,
                wa_id=wa_id,
                customer_id=customer.id,
                conversation_id=conversation.id,
            )
        else:
            conversation = await ScopedRepository(self.session, self.ctx, Conversation).get(
                contact.conversation_id, for_update=True
            )
            if conversation.status == ConversationStatus.CLOSED:
                conversation = await ScopedRepository(self.session, self.ctx, Conversation).create(
                    customer_id=contact.customer_id, channel="whatsapp"
                )
                contact.conversation_id = conversation.id
        from app.repositories.conversations import ConversationRepository

        previous_last = conversation.last_customer_msg_at
        message = await ConversationRepository(self.session, self.ctx).receive(
            conversation.id, text, key
        )
        message.created_at = timestamp
        message.content_type, message.attachments = kind, attachments
        conversation.last_customer_msg_at = max(timestamp, previous_last or timestamp)
        if text.strip().casefold() in {"stop", "unsubscribe", "cancel messages", "band karo"}:
            contact.opted_out = True
            contact.opted_in_at = None
        if contact.opted_out:
            from app.db.models.conversation import ConversationMode

            conversation.mode = ConversationMode.HUMAN
        await self.session.flush()
        return message

    async def templates(self, account_id: UUID) -> list[WhatsAppTemplate]:
        await self.get(account_id)
        return list(
            await self.session.scalars(
                select(WhatsAppTemplate)
                .where(
                    WhatsAppTemplate.tenant_id == self.ctx.tenant_id,
                    WhatsAppTemplate.account_id == account_id,
                )
                .order_by(WhatsAppTemplate.name, WhatsAppTemplate.language)
                .limit(500)
            )
        )

    async def queue(
        self, message: Message, template_id: UUID | None = None
    ) -> ChannelDelivery | None:
        if message.tenant_id != self.ctx.tenant_id or message.direction != Direction.OUT:
            raise DomainError("Only scoped outbound messages can be queued", 409)
        conversation = await ScopedRepository(self.session, self.ctx, Conversation).get(
            message.conversation_id
        )
        if conversation.channel == "web":
            return None
        if conversation.channel != "whatsapp":
            raise DomainError("Unsupported delivery channel", 409)
        contact = await self.contact(conversation.id)
        account = await self.get(contact.account_id)
        blocked = account.status != AccountStatus.ACTIVE or contact.opted_out
        if template_id:
            template = await ScopedRepository(self.session, self.ctx, WhatsAppTemplate).get(
                template_id
            )
            if template.account_id != account.id:
                raise NotFound()
        return (
            await self.session.scalars(
                insert(ChannelDelivery)
                .values(
                    tenant_id=self.ctx.tenant_id,
                    account_id=account.id,
                    message_id=message.id,
                    template_id=template_id,
                    status=DeliveryStatus.BLOCKED if blocked else DeliveryStatus.QUEUED,
                    last_error="account_disabled_or_opted_out" if blocked else None,
                    attempts=0,
                    created_at=datetime.now(UTC),
                    next_attempt_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(
                    index_elements=[ChannelDelivery.tenant_id, ChannelDelivery.message_id]
                )
                .returning(ChannelDelivery)
            )
        ).one_or_none()

    async def has_earlier_delivery(self, delivery: ChannelDelivery, conversation_id: UUID) -> bool:
        earlier = await self.session.scalar(
            select(ChannelDelivery.id)
            .join(
                Message,
                (Message.tenant_id == ChannelDelivery.tenant_id)
                & (Message.id == ChannelDelivery.message_id),
            )
            .where(
                ChannelDelivery.tenant_id == self.ctx.tenant_id,
                Message.tenant_id == self.ctx.tenant_id,
                Message.conversation_id == conversation_id,
                ChannelDelivery.created_at < delivery.created_at,
                ChannelDelivery.status.in_(
                    [
                        DeliveryStatus.QUEUED,
                        DeliveryStatus.RETRY,
                        DeliveryStatus.SENDING,
                        DeliveryStatus.UNCERTAIN,
                    ]
                ),
            )
            .limit(1)
        )
        return earlier is not None

    async def recover_interrupted(self, before: datetime) -> None:
        records = list(
            await self.session.scalars(
                select(ChannelDelivery)
                .where(
                    ChannelDelivery.tenant_id == self.ctx.tenant_id,
                    ChannelDelivery.status == DeliveryStatus.SENDING,
                    ChannelDelivery.updated_at < before,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for delivery in records:
            delivery.status, delivery.last_error = (
                DeliveryStatus.UNCERTAIN,
                "interrupted_send_requires_reconciliation",
            )
        await self.session.flush()

    async def deliveries(self, limit: int = 100) -> list[ChannelDelivery]:
        return await ScopedRepository(self.session, self.ctx, ChannelDelivery).list(limit)

    async def status(self, account_id: UUID, provider_id: str, status: str) -> None:
        await self.get(account_id)
        if status not in {"sent", "delivered", "read", "failed"}:
            return
        await self.session.execute(
            insert(ChannelStatusReceipt)
            .values(
                tenant_id=self.ctx.tenant_id,
                account_id=account_id,
                provider_message_id=provider_id,
                status=status,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ChannelStatusReceipt.tenant_id,
                    ChannelStatusReceipt.account_id,
                    ChannelStatusReceipt.provider_message_id,
                    ChannelStatusReceipt.status,
                ]
            )
        )
        delivery = (
            await self.session.scalars(
                select(ChannelDelivery)
                .where(
                    ChannelDelivery.tenant_id == self.ctx.tenant_id,
                    ChannelDelivery.account_id == account_id,
                    ChannelDelivery.provider_message_id == provider_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if delivery is None:
            return
        order = [DeliveryStatus.SENT, DeliveryStatus.DELIVERED, DeliveryStatus.READ]
        if status in {"sent", "delivered", "read"}:
            incoming = DeliveryStatus(status)
            if delivery.status not in order or order.index(incoming) > order.index(delivery.status):
                delivery.status = incoming
        elif status == "failed" and delivery.status not in {
            DeliveryStatus.DELIVERED,
            DeliveryStatus.READ,
        }:
            delivery.status, delivery.last_error = DeliveryStatus.FAILED, "provider_delivery_failed"

    async def reconcile(self, delivery: ChannelDelivery) -> None:
        if delivery.provider_message_id is None:
            return
        statuses = set(
            await self.session.scalars(
                select(ChannelStatusReceipt.status).where(
                    ChannelStatusReceipt.tenant_id == self.ctx.tenant_id,
                    ChannelStatusReceipt.account_id == delivery.account_id,
                    ChannelStatusReceipt.provider_message_id == delivery.provider_message_id,
                )
            )
        )
        if "read" in statuses:
            delivery.status = DeliveryStatus.READ
        elif "delivered" in statuses and delivery.status != DeliveryStatus.READ:
            delivery.status = DeliveryStatus.DELIVERED
        elif "failed" in statuses and delivery.status not in {
            DeliveryStatus.DELIVERED,
            DeliveryStatus.READ,
        }:
            delivery.status, delivery.last_error = DeliveryStatus.FAILED, "provider_delivery_failed"

    async def reconcile_pending(self) -> None:
        deliveries = list(
            await self.session.scalars(
                select(ChannelDelivery)
                .where(
                    ChannelDelivery.tenant_id == self.ctx.tenant_id,
                    ChannelDelivery.status.in_([DeliveryStatus.SENT, DeliveryStatus.DELIVERED]),
                )
                .order_by(ChannelDelivery.updated_at)
                .limit(200)
                .with_for_update(skip_locked=True)
            )
        )
        for delivery in deliveries:
            await self.reconcile(delivery)


async def due_deliveries(
    session: AsyncSession, ctx: TenantContext, now: datetime
) -> list[tuple[UUID, UUID]]:
    return list(
        (
            await session.execute(
                select(ChannelDelivery.tenant_id, ChannelDelivery.id)
                .where(
                    ChannelDelivery.tenant_id == ctx.tenant_id,
                    ChannelDelivery.status.in_([DeliveryStatus.QUEUED, DeliveryStatus.RETRY]),
                    ChannelDelivery.next_attempt_at <= now,
                )
                .order_by(ChannelDelivery.next_attempt_at)
                .limit(200)
            )
        ).tuples()
    )
