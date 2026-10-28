from typing import Annotated, cast
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import PlainTextResponse, Response

from app.channels.service import WhatsAppService, ingest_webhook, verify_challenge
from app.core.deps import Config, Context, Owner, Session
from app.core.errors import DomainError
from app.repositories.channels import ChannelRepository
from app.schemas.whatsapp import (
    AccountChange,
    AccountView,
    ConnectWhatsApp,
    ConsentChange,
    ConsentView,
    DeliveryResolution,
    DeliveryView,
    FollowupOptions,
    SetupView,
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
    account_id: UUID,
    body: AccountChange,
    request: Request,
    session: Session,
    ctx: Owner,
    config: Config,
) -> AccountView:
    return AccountView.model_validate(
        await service(request, session, ctx, config).change_account(account_id, body.status)
    )


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
async def deliveries(
    request: Request, session: Session, ctx: Context, config: Config
) -> list[DeliveryView]:
    return await service(request, session, ctx, config).delivery_views()


@router.get("/conversations/{conversation_id}/whatsapp-consent", response_model=ConsentView)
async def consent(
    conversation_id: UUID, request: Request, session: Session, ctx: Context, config: Config
) -> ConsentView:
    return await service(request, session, ctx, config).consent_view(conversation_id)


@router.put("/conversations/{conversation_id}/whatsapp-consent", response_model=ConsentView)
async def set_consent(
    conversation_id: UUID,
    body: ConsentChange,
    request: Request,
    session: Session,
    ctx: Owner,
    config: Config,
) -> ConsentView:
    return await service(request, session, ctx, config).record_consent(conversation_id, body)


@router.get("/channels/whatsapp/setup", response_model=SetupView)
async def setup(request: Request, session: Session, config: Config, ctx: Owner) -> SetupView:
    return service(request, session, ctx, config).setup_view()


@router.post("/channels/whatsapp/deliveries/{delivery_id}/resolve", response_model=DeliveryView)
async def resolve(
    delivery_id: UUID,
    body: DeliveryResolution,
    request: Request,
    session: Session,
    ctx: Owner,
    config: Config,
) -> DeliveryView:
    return await service(request, session, ctx, config).resolve(delivery_id, body)


@router.get("/followups/{followup_id}/whatsapp-options", response_model=FollowupOptions)
async def options(
    followup_id: UUID, request: Request, session: Session, ctx: Owner, config: Config
) -> FollowupOptions:
    return await service(request, session, ctx, config).followup_options(followup_id)


@router.get("/conversations/{conversation_id}/messages/{message_id}/media/{media_id}")
async def media(
    conversation_id: UUID,
    message_id: UUID,
    media_id: str,
    request: Request,
    session: Session,
    ctx: Context,
    config: Config,
) -> Response:
    content, filename = await service(request, session, ctx, config).media(
        conversation_id, message_id, media_id
    )
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
