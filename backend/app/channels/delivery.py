from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.guardrails import check_prices
from app.channels.service import WhatsAppService, require_send, usable_template
from app.channels.whatsapp import GraphAmbiguous, GraphRejected
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models import ChannelDelivery, Message
from app.db.models.channel import DeliveryStatus
from app.quotes.pdf import quote_allowed_prices
from app.quotes.service import QuoteService
from app.repositories.channels import ChannelRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.quotes import QuoteRepository
from app.repositories.scoped import ScopedRepository
from app.tools.inbox_prices import reply_prices


class DeliveryService:
    def __init__(
        self,
        session: AsyncSession,
        ctx: TenantContext,
        config: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.session, self.ctx, self.config, self.transport = session, ctx, config, transport
        self.channels = ChannelRepository(session, ctx)
        self.deliveries = ScopedRepository(session, ctx, ChannelDelivery)

    @staticmethod
    def check_current_message(message: Message, conversation: object) -> None:
        from app.db.models import Conversation
        from app.db.models.conversation import ConversationMode, SenderType

        assert isinstance(conversation, Conversation)
        handoff = any(entry.get("handoff") is True for entry in message.attachments)
        automated = message.sender_type == SenderType.AI or any(
            entry.get("automated") is True for entry in message.attachments
        )
        if automated and not handoff and conversation.mode != ConversationMode.AI:
            raise DomainError("Automation stopped after takeover", 409)
        if message.external_id and message.external_id.startswith("followup:"):
            if conversation.mode != ConversationMode.AI or (
                conversation.last_customer_msg_at
                and conversation.last_customer_msg_at > message.created_at
            ):
                raise DomainError(
                    "Follow-up needs a new review after customer activity or takeover", 409
                )

    async def send(self, delivery_id: UUID) -> None:
        initial = await self.deliveries.get(delivery_id)
        message = await ScopedRepository(self.session, self.ctx, Message).get(initial.message_id)
        conversation = await ConversationRepository(self.session, self.ctx).get(
            message.conversation_id, for_update=True
        )
        delivery = await self.deliveries.get(delivery_id, for_update=True)
        if delivery.status not in {
            DeliveryStatus.QUEUED,
            DeliveryStatus.RETRY,
        } or delivery.next_attempt_at > datetime.now(UTC):
            return
        if await self.channels.has_earlier_delivery(delivery, conversation.id):
            return
        delivery.status = DeliveryStatus.SENDING
        delivery.attempts += 1
        delivery.last_error = None
        await self.session.commit()
        sending = False
        try:
            self.check_current_message(message, conversation)
            template = await require_send(
                self.session, self.ctx, self.config, conversation.id, delivery.template_id
            )
            contact = await self.channels.contact(conversation.id)
            if delivery.account_id != contact.account_id:
                raise DomainError("Delivery account does not match conversation", 409)
            account = await self.channels.get(delivery.account_id)
            graph = WhatsAppService(self.session, self.ctx, self.config, self.transport).graph(
                account
            )
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": contact.wa_id,
            }
            pdf: bytes | None = None
            if template:
                # Revalidate remote approval/content immediately before any template delivery.
                values = await graph.list_resources(
                    account.business_account_id + "/message_templates",
                    "id,name,language,status,components",
                )
                latest = next(
                    (value for value in values if value.get("id") == template.provider_id), None
                )
                if (
                    latest is None
                    or latest.get("name") != template.name
                    or latest.get("language") != template.language
                    or usable_template(latest) != (template.body_text, True)
                    or message.content != template.body_text
                ):
                    template.usable = False
                    raise DomainError(
                        "Template approval or content changed; sync and review again", 409
                    )
                check_prices(template.body_text, set())
                payload.update(
                    type="template",
                    template={"name": template.name, "language": {"code": template.language}},
                )
            else:
                allowed = await reply_prices(self.session, self.ctx, self.config, conversation.id)
                quote_ref = next(
                    (
                        entry.get("quote_id")
                        for entry in message.attachments
                        if entry.get("quote_id")
                    ),
                    None,
                )
                if message.content_type == "document":
                    if not isinstance(quote_ref, str):
                        raise DomainError("Only generated quote PDFs can be delivered", 409)
                    quote_id = UUID(quote_ref)
                    quote = await QuoteRepository(self.session, self.ctx).get(quote_id)
                    if (
                        quote.conversation_id != conversation.id
                        or quote.sent_at is None
                        or quote.valid_until <= datetime.now(UTC)
                    ):
                        raise DomainError("Quote is not approved for this conversation", 409)
                    service = QuoteService(self.session, self.ctx, self.config)
                    allowed = quote_allowed_prices(await service.view(quote.id))
                    pdf = await service.pdf(quote.id)
                    if len(message.content) > 1024:
                        raise DomainError("Document caption exceeds WhatsApp limit")
                check_prices(message.content, allowed)
                buttons = next(
                    (entry.get("buttons") for entry in message.attachments if entry.get("buttons")),
                    None,
                )
                if buttons:
                    from app.schemas.chat import ReplyButton

                    if (
                        not isinstance(buttons, list)
                        or len(buttons) > 3
                        or len(message.content) > 1024
                    ):
                        raise DomainError("Invalid interactive message")
                    typed = [ReplyButton.model_validate(button) for button in buttons]
                    for button in typed:
                        check_prices(button.title, set())
                    payload.update(
                        type="interactive",
                        interactive={
                            "type": "button",
                            "body": {"text": message.content},
                            "action": {
                                "buttons": [
                                    {"type": "reply", "reply": button.model_dump()}
                                    for button in typed
                                ]
                            },
                        },
                    )
                else:
                    payload.update(
                        type="text", text={"body": message.content, "preview_url": False}
                    )
            delivery.status = DeliveryStatus.SENDING
            delivery.last_error = None
            await self.session.commit()
            if pdf is not None:
                media_id = await graph.upload_pdf(account.external_id, pdf)
                payload.update(
                    type="document",
                    document={
                        "id": media_id,
                        "caption": message.content,
                        "filename": "quotation.pdf",
                    },
                )
                payload.pop("text", None)
            # Window/consent may change during media upload or registry retrieval.
            conversation = await ConversationRepository(self.session, self.ctx).get(
                message.conversation_id
            )
            self.check_current_message(message, conversation)
            await require_send(
                self.session, self.ctx, self.config, conversation.id, delivery.template_id
            )
            await self.session.commit()
            sending = True
            provider_id = await graph.send(account.external_id, payload)
        except GraphRejected as error:
            delivery = await self.deliveries.get(delivery_id, for_update=True)
            transient = error.provider_status == 429 or error.provider_status >= 500
            delivery.status = (
                DeliveryStatus.RETRY
                if transient and delivery.attempts < self.config.whatsapp_max_attempts
                else DeliveryStatus.FAILED
            )
            delivery.last_error = f"provider_http_{error.provider_status}_code_{error.code}"
            delivery.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=max(error.retry_after, min(3600, 2 ** min(delivery.attempts, 12)))
            )
            await self.session.commit()
            self.log(delivery)
            return
        except (httpx.TransportError, GraphAmbiguous) as error:
            delivery = await self.deliveries.get(delivery_id, for_update=True)
            safe = not sending or isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))
            delivery.status = (
                DeliveryStatus.RETRY
                if safe and delivery.attempts < self.config.whatsapp_max_attempts
                else DeliveryStatus.FAILED
                if safe
                else DeliveryStatus.UNCERTAIN
            )
            delivery.last_error = (
                "transport_retry" if safe else "acceptance_uncertain_do_not_resend"
            )
            delivery.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(3600, 2 ** min(delivery.attempts, 12))
            )
            await self.session.commit()
            self.log(delivery)
            return
        except (DomainError, ValueError, ValidationError):
            delivery = await self.deliveries.get(delivery_id, for_update=True)
            delivery.status, delivery.last_error = (
                DeliveryStatus.BLOCKED,
                "policy_or_content_requires_review",
            )
            await self.session.commit()
            self.log(delivery)
            return
        delivery = await self.deliveries.get(delivery_id, for_update=True)
        delivery.provider_message_id, delivery.status = provider_id, DeliveryStatus.SENT
        conversation = await ConversationRepository(self.session, self.ctx).get(
            message.conversation_id, for_update=True
        )
        conversation.last_business_msg_at = datetime.now(UTC)
        await self.channels.reconcile(delivery)
        await self.session.commit()

    @staticmethod
    def log(delivery: ChannelDelivery) -> None:
        structlog.get_logger().warning(
            "whatsapp_delivery_attention",
            delivery_id=str(delivery.id),
            tenant_id=str(delivery.tenant_id),
            status=delivery.status.value,
            error=delivery.last_error,
        )
