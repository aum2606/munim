"""Sending stored messages to customers over WhatsApp."""

import uuid
from datetime import UTC, datetime

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp import WhatsAppClient, WhatsAppError, window_open
from app.core.config import Settings
from app.core.context import TenantContext
from app.core.crypto import decrypt_credentials
from app.db.models import Message
from app.repositories.channels import ChannelAccountRepository
from app.repositories.chat import ChatRepository
from app.services.quotes import QuoteService

log = structlog.get_logger()


async def whatsapp_client(
    session: AsyncSession, ctx: TenantContext, settings: Settings, http: httpx.AsyncClient
) -> WhatsAppClient | None:
    """The business's WhatsApp client, or None when no active number is connected."""
    account = await ChannelAccountRepository(session, ctx).get()
    if account is None or not account.is_active:
        return None
    token = str(decrypt_credentials(settings, account.credentials_encrypted).get("access_token"))
    return WhatsAppClient(http, settings.whatsapp_api_version, account.external_id, token)


async def deliver_message(
    session: AsyncSession,
    ctx: TenantContext,
    settings: Settings,
    http: httpx.AsyncClient,
    message_id: str,
) -> None:
    """Send one stored outbound message. Safe to run twice: a message that already has Meta's id
    is never sent again."""
    chat = ChatRepository(session, ctx)
    message = await chat.get_message(uuid.UUID(message_id))
    if message is None or message.external_id is not None:
        return
    conversation = await chat.get_conversation(message.conversation_id)
    customer = await chat.get_customer(conversation.customer_id) if conversation else None
    if conversation is None or customer is None or not customer.phone:
        return _fail(message, "no_recipient")

    if not window_open(conversation.last_customer_msg_at, datetime.now(UTC)):
        # Meta only allows approved templates now. We never send one, so say so instead of failing
        # silently: the dashboard shows it and the owner can reply from their own phone.
        message.delivery_status = "window_closed"
        return
    client = await whatsapp_client(session, ctx, settings, http)
    if client is None:
        return _fail(message, "no_whatsapp_account")
    try:
        if message.quote_id is not None:  # the approved quotation goes as a PDF document
            quotes = QuoteService(session, ctx, settings)
            view = await quotes.view(message.quote_id)
            wa_id = await client.send_document(
                customer.phone,
                await quotes.pdf(message.quote_id),
                f"{view.quote.quote_number.replace('/', '-')}.pdf",
                message.content,
            )
        else:
            wa_id = await client.send_text(customer.phone, message.content)
    except WhatsAppError as exc:
        if not exc.permanent:
            raise  # the job queue retries with backoff, then dead-letters
        return _fail(message, exc.detail or f"http_{exc.status}")
    message.external_id = wa_id
    message.delivery_status = "sent"


def _fail(message: Message, reason: str) -> None:
    log.warning("delivery_failed", reason=reason)
    message.delivery_status = "failed"
    message.delivery_error = reason[:200]
