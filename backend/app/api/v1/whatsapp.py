from typing import Annotated, cast
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import PlainTextResponse

from app.channels.service import WhatsAppService, ingest_webhook, verify_challenge
from app.core.deps import Config, Context, Owner, Session
from app.core.errors import DomainError
from app.repositories.channels import ChannelRepository
from app.repositories.conversations import ConversationRepository
from app.schemas.whatsapp import (
    AccountChange,
    AccountView,
    ConnectWhatsApp,
    ConsentChange,
    ConsentView,
    DeliveryView,
    TemplateView,
)
from app.workers.queue import JobQueue

router = APIRouter()


def service(request: Request, session: Session, ctx: Context, config: Config) -> WhatsAppService:
    return WhatsAppService(
        session,
        ctx,
        config,
        cast(
            httpx.AsyncBaseTransport | None, getattr(request.app.state, "whatsapp_transport", None)
        ),
    )


@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
async def challenge(
    config: Config,
    mode: Annotated[str, Query(alias="hub.mode", max_length=30)],
    token: Annotated[str, Query(alias="hub.verify_token", max_length=512)],
    challenge: Annotated[str, Query(alias="hub.challenge", max_length=512)],
) -> str:
    return verify_challenge(config, mode, token, challenge)


@router.post("/webhooks/whatsapp")
async def webhook(
    request: Request,
    session: Session,
    config: Config,
    signature: Annotated[str, Header(alias="X-Hub-Signature-256", max_length=100)] = "",
) -> dict[str, str]:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024 * 1024:
            raise DomainError("Webhook body too large", 413)
    await ingest_webhook(
        session, config, cast(JobQueue, request.app.state.jobs), bytes(raw), signature
    )
    return {"status": "accepted"}


@router.get("/channels/whatsapp", response_model=list[AccountView])
async def accounts(session: Session, ctx: Owner) -> list[AccountView]:
    return [
        AccountView.model_validate(account)
        for account in await ChannelRepository(session, ctx).list()
    ]


@router.post("/channels/whatsapp", response_model=AccountView, status_code=201)
async def connect(
    body: ConnectWhatsApp, request: Request, session: Session, ctx: Owner, config: Config
) -> AccountView:
    return AccountView.model_validate(await service(request, session, ctx, config).connect(body))


@router.patch("/channels/whatsapp/{account_id}", response_model=AccountView)
async def change(
    account_id: UUID, body: AccountChange, session: Session, ctx: Owner
) -> AccountView:
    account = await ChannelRepository(session, ctx).get(account_id, for_update=True)
    account.status = body.status
    await session.commit()
    return AccountView.model_validate(account)


@router.get("/channels/whatsapp/{account_id}/templates", response_model=list[TemplateView])
async def templates(account_id: UUID, session: Session, ctx: Context) -> list[TemplateView]:
    return [
        TemplateView.model_validate(template)
        for template in await ChannelRepository(session, ctx).templates(account_id)
    ]


@router.post("/channels/whatsapp/{account_id}/templates/sync", response_model=list[TemplateView])
async def sync(
    account_id: UUID, request: Request, session: Session, ctx: Owner, config: Config
) -> list[TemplateView]:
    return [
        TemplateView.model_validate(template)
        for template in await service(request, session, ctx, config).sync_templates(account_id)
    ]


@router.get("/channels/whatsapp/deliveries", response_model=list[DeliveryView])
async def deliveries(session: Session, ctx: Context) -> list[DeliveryView]:
    return [
        DeliveryView.model_validate(delivery)
        for delivery in await ChannelRepository(session, ctx).deliveries()
    ]


@router.get("/conversations/{conversation_id}/whatsapp-consent", response_model=ConsentView)
async def consent(conversation_id: UUID, session: Session, ctx: Context) -> ConsentView:
    await ConversationRepository(session, ctx).get(conversation_id)
    return ConsentView.model_validate(
        await ChannelRepository(session, ctx).contact(conversation_id)
    )


@router.put("/conversations/{conversation_id}/whatsapp-consent", response_model=ConsentView)
async def set_consent(
    conversation_id: UUID, body: ConsentChange, session: Session, ctx: Owner
) -> ConsentView:
    from datetime import UTC, datetime

    await ConversationRepository(session, ctx).get(conversation_id, for_update=True)
    contact = await ChannelRepository(session, ctx).contact(conversation_id)
    contact.opted_in_at = datetime.now(UTC) if body.opted_in else None
    contact.opted_out, contact.consent_note, contact.consent_by = (
        not body.opted_in,
        body.note,
        ctx.user_id,
    )
    await session.commit()
    return ConsentView.model_validate(contact)
