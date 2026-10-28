import hmac
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import Select, String, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.base import TenantRecord
from app.db.models import (
    AgentRun,
    AnalyticsEvent,
    ChannelDelivery,
    ChannelStatusReceipt,
    Chunk,
    Conversation,
    Customer,
    Document,
    Followup,
    Handoff,
    KnowledgeGap,
    Lead,
    LeadEvent,
    Message,
    Quote,
    QuoteItem,
    ReplyDraft,
    TenantSettings,
    WeeklyDigest,
    WhatsAppContact,
    WidgetSession,
)
from app.db.models.channel import DeliveryStatus
from app.db.models.privacy import PrivacyErasure
from app.repositories.scoped import ScopedRepository


def fingerprint(secret: str, tenant_id: UUID, value: str) -> str:
    return hmac.new(secret.encode(), f"{tenant_id}:{value}".encode(), sha256).hexdigest()


class PrivacyRepository(ScopedRepository[PrivacyErasure]):
    def __init__(self, session: AsyncSession, ctx: TenantContext, secret: str) -> None:
        super().__init__(session, ctx, PrivacyErasure)
        self.secret = secret

    async def customers(self, query: str) -> list[Customer]:
        statement = select(Customer).where(Customer.tenant_id == self.ctx.tenant_id)
        if query:
            statement = statement.where(
                or_(
                    Customer.name.icontains(query, autoescape=True),
                    Customer.phone.icontains(query, autoescape=True),
                    Customer.email.icontains(query, autoescape=True),
                    Customer.id.cast(String).icontains(query, autoescape=True),
                    select(Conversation.id)
                    .where(
                        Conversation.tenant_id == self.ctx.tenant_id,
                        Conversation.customer_id == Customer.id,
                        Conversation.id.cast(String) == query,
                    )
                    .exists(),
                )
            )
        return list(
            await self.session.scalars(statement.order_by(Customer.created_at.desc()).limit(200))
        )

    async def pending(self) -> list[PrivacyErasure]:
        return list(
            await self.session.scalars(
                select(PrivacyErasure)
                .where(
                    PrivacyErasure.tenant_id == self.ctx.tenant_id,
                    PrivacyErasure.status == "pending_files",
                )
                .order_by(PrivacyErasure.created_at)
                .limit(100)
            )
        )

    async def replay_erased(self, account_id: UUID, wa_id: str, timestamp: datetime) -> bool:
        tag = fingerprint(self.secret, self.ctx.tenant_id, f"wa:{account_id}:{wa_id}")
        return bool(
            await self.session.scalar(
                select(PrivacyErasure.id)
                .where(
                    PrivacyErasure.tenant_id == self.ctx.tenant_id,
                    PrivacyErasure.channel_fingerprints.contains([tag]),
                    PrivacyErasure.created_at >= timestamp,
                )
                .limit(1)
            )
        )

    async def erase(self, customer_id: UUID) -> PrivacyErasure:
        tag = fingerprint(self.secret, self.ctx.tenant_id, str(customer_id))
        previous = await self.session.scalar(
            select(PrivacyErasure).where(
                PrivacyErasure.tenant_id == self.ctx.tenant_id,
                PrivacyErasure.customer_fingerprint == tag,
            )
        )
        if previous:
            return previous
        await ScopedRepository(self.session, self.ctx, Customer).get(customer_id, for_update=True)
        conversations = list(
            await self.session.scalars(
                select(Conversation)
                .where(
                    Conversation.tenant_id == self.ctx.tenant_id,
                    Conversation.customer_id == customer_id,
                )
                .order_by(Conversation.id)
                .with_for_update()
            )
        )
        conversation_ids = [record.id for record in conversations]
        # Lock conversations before the audit barrier, matching existing workflow writers.
        settings = (
            await self.session.scalars(
                select(TenantSettings)
                .where(TenantSettings.tenant_id == self.ctx.tenant_id)
                .with_for_update()
            )
        ).one()
        message_ids = select(Message.id).where(
            Message.tenant_id == self.ctx.tenant_id, Message.conversation_id.in_(conversation_ids)
        )
        deliveries = list(
            await self.session.scalars(
                select(ChannelDelivery).where(
                    ChannelDelivery.tenant_id == self.ctx.tenant_id,
                    ChannelDelivery.message_id.in_(message_ids),
                )
            )
        )
        if any(
            record.status in {DeliveryStatus.SENDING, DeliveryStatus.UNCERTAIN}
            for record in deliveries
        ):
            raise DomainError(
                "Resolve in-flight or uncertain channel deliveries before erasure", 409
            )
        quotes = list(
            await self.session.scalars(
                select(Quote).where(
                    Quote.tenant_id == self.ctx.tenant_id,
                    Quote.conversation_id.in_(conversation_ids),
                )
            )
        )
        gaps = list(
            await self.session.scalars(
                select(KnowledgeGap).where(
                    KnowledgeGap.tenant_id == self.ctx.tenant_id,
                    KnowledgeGap.example_message_id.in_(message_ids),
                )
            )
        )
        document_ids = [gap.converted_document_id for gap in gaps if gap.converted_document_id]
        documents = list(
            await self.session.scalars(
                select(Document).where(
                    Document.tenant_id == self.ctx.tenant_id, Document.id.in_(document_ids)
                )
            )
        )
        contacts = list(
            await self.session.scalars(
                select(WhatsAppContact).where(
                    WhatsAppContact.tenant_id == self.ctx.tenant_id,
                    WhatsAppContact.customer_id == customer_id,
                )
            )
        )
        erasure = await self.create(
            customer_fingerprint=tag,
            channel_fingerprints=[
                fingerprint(
                    self.secret, self.ctx.tenant_id, f"wa:{contact.account_id}:{contact.wa_id}"
                )
                for contact in contacts
            ],
            files=[f"{self.ctx.tenant_id}/quotes/{quote.id}-*.pdf" for quote in quotes]
            + [document.storage_path for document in documents],
            counts={"conversations": len(conversations), "quotes": len(quotes)},
            created_at=datetime.now(UTC),
        )
        settings.last_erasure_at = erasure.created_at
        lead_ids = select(Lead.id).where(
            Lead.tenant_id == self.ctx.tenant_id, Lead.conversation_id.in_(conversation_ids)
        )
        quote_ids = [quote.id for quote in quotes]
        # Every mutation is explicitly scoped, including FK cycle-breaking and cache invalidation.
        for delivery in deliveries:
            await self.session.execute(
                delete(ChannelStatusReceipt).where(
                    ChannelStatusReceipt.tenant_id == self.ctx.tenant_id,
                    ChannelStatusReceipt.account_id == delivery.account_id,
                    ChannelStatusReceipt.provider_message_id == delivery.provider_message_id,
                )
            )
        await self.session.execute(
            delete(ChannelDelivery).where(
                ChannelDelivery.tenant_id == self.ctx.tenant_id,
                ChannelDelivery.message_id.in_(message_ids),
            )
        )
        deletions: list[
            tuple[type[TenantRecord], InstrumentedAttribute[UUID], list[UUID] | Select[tuple[UUID]]]
        ] = [
            (QuoteItem, QuoteItem.quote_id, quote_ids),
            (Quote, Quote.conversation_id, conversation_ids),
            (Followup, Followup.lead_id, lead_ids),
            (LeadEvent, LeadEvent.lead_id, lead_ids),
            (Lead, Lead.conversation_id, conversation_ids),
            (ReplyDraft, ReplyDraft.conversation_id, conversation_ids),
            (Handoff, Handoff.conversation_id, conversation_ids),
            (WhatsAppContact, WhatsAppContact.customer_id, [customer_id]),
            (WidgetSession, WidgetSession.conversation_id, conversation_ids),
        ]
        for model, column, identifiers in deletions:
            await self.session.execute(
                delete(model).where(model.tenant_id == self.ctx.tenant_id, column.in_(identifiers))
            )
        await self.session.execute(
            delete(KnowledgeGap).where(
                KnowledgeGap.tenant_id == self.ctx.tenant_id,
                KnowledgeGap.example_message_id.in_(message_ids),
            )
        )
        # Derived owner traces may contain summaries from several conversations; purge these too.
        await self.session.execute(
            update(Message)
            .where(
                Message.tenant_id == self.ctx.tenant_id,
                Message.conversation_id.in_(conversation_ids),
            )
            .values(agent_run_id=None, in_reply_to_id=None)
        )
        await self.session.execute(
            delete(AgentRun).where(
                AgentRun.tenant_id == self.ctx.tenant_id,
                or_(AgentRun.message_id.in_(message_ids), AgentRun.message_id.is_(None)),
            )
        )
        await self.session.execute(
            delete(Message).where(
                Message.tenant_id == self.ctx.tenant_id,
                Message.conversation_id.in_(conversation_ids),
            )
        )
        await self.session.execute(
            delete(AnalyticsEvent).where(
                AnalyticsEvent.tenant_id == self.ctx.tenant_id,
                AnalyticsEvent.properties["conversation_id"].astext.in_(
                    [str(value) for value in conversation_ids]
                ),
            )
        )
        await self.session.execute(
            delete(WeeklyDigest).where(WeeklyDigest.tenant_id == self.ctx.tenant_id)
        )
        await self.session.execute(
            delete(Conversation).where(
                Conversation.tenant_id == self.ctx.tenant_id, Conversation.id.in_(conversation_ids)
            )
        )
        await self.session.execute(
            delete(Chunk).where(
                Chunk.tenant_id == self.ctx.tenant_id, Chunk.document_id.in_(document_ids)
            )
        )
        await self.session.execute(
            delete(Document).where(
                Document.tenant_id == self.ctx.tenant_id, Document.id.in_(document_ids)
            )
        )
        await self.session.execute(
            delete(Customer).where(
                Customer.tenant_id == self.ctx.tenant_id, Customer.id == customer_id
            )
        )
        await self.session.flush()
        return erasure
