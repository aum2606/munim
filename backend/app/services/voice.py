"""Voice notes: download, transcribe, then treat the words like a typed message."""

import uuid

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp import WhatsAppError
from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import Conversation, SenderType
from app.jobs.queue import enqueue
from app.llm.transcriber import Transcriber
from app.orchestrator.messages import canned, voice_confirm_message
from app.repositories.chat import ChatRepository
from app.services.delivery import whatsapp_client
from app.services.outbound import send_to_customer

log = structlog.get_logger()

# The language only picks which fixed reply to send. Roman script, because that is how most people
# write on WhatsApp; the router still detects the real language of the words themselves.
_REPLY_LANGUAGE = {"hi": "hinglish", "gu": "gujlish"}


async def transcribe_message(
    session: AsyncSession,
    ctx: TenantContext,
    settings: Settings,
    http: httpx.AsyncClient,
    transcriber: Transcriber,
    message_id: str,
) -> None:
    """Safe to run twice: a note that already has a transcript is left alone."""
    chat = ChatRepository(session, ctx)
    message = await chat.get_message(uuid.UUID(message_id))
    if message is None or message.media_id is None or message.transcript_confidence is not None:
        return
    conversation = await chat.get_conversation(message.conversation_id)
    if conversation is None:
        return
    language = await chat.last_language(conversation.id) or "en"

    text, confidence = "", 0.0
    client = await whatsapp_client(session, ctx, settings, http)
    if client is not None:
        try:
            audio, mime = await client.download_media(
                message.media_id, settings.max_voice_note_mb * 1024 * 1024
            )
            result = await transcriber.transcribe(audio, mime)
            text, confidence = result.text, result.confidence
            language = _REPLY_LANGUAGE.get(result.language, "en")
        except WhatsAppError as exc:
            if not exc.permanent:
                raise  # expired URL or Meta hiccup: retry
            log.warning("voice_download_failed", status=exc.status)
        except Exception as exc:  # a corrupt or unsupported file must not retry forever
            log.warning("voice_transcription_failed", error=type(exc).__name__)

    message.transcript_confidence = confidence  # also marks this note as processed
    if not text:
        await _reply(chat, conversation, message.id, canned("voice_failed", language), language)
    elif confidence < settings.stt_confidence_threshold:
        # Not sure enough to act on: show what we heard and let the customer confirm or retype.
        message.content = text
        await _reply(
            chat, conversation, message.id, voice_confirm_message(language, text), language
        )
    else:
        message.content = text
        await enqueue(session, ctx, "process_message", {"conversation_id": str(conversation.id)})
        return
    await chat.mark_handled([message.id])


async def _reply(
    chat: ChatRepository,
    conversation: Conversation,
    message_id: uuid.UUID,
    content: str,
    language: str,
) -> None:
    await send_to_customer(
        chat,
        conversation,
        sender_type=SenderType.AI,
        content=content,
        language=language,
        reply_to_id=message_id,
    )
