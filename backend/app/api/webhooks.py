"""Inbound webhooks. Not under /api/v1 and not authenticated by a user: Meta proves who it is by
signing the raw body, and Meta's subscription check uses the verify token."""

import json
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from app.channels.whatsapp import parse_webhook, verify_challenge, verify_signature
from app.core.deps import SessionDep, SettingsDep
from app.core.errors import FileRejectedError, ForbiddenError, RateLimitedError
from app.core.ratelimit import client_ip, rate_limit
from app.services.inbound import InboundService

log = structlog.get_logger()
router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"],
    include_in_schema=False,
    dependencies=[Depends(rate_limit("webhook", 1200, 60))],  # generous: Meta sends in bursts
)

MAX_BODY_BYTES = 3 * 1024 * 1024  # Meta documents payloads of up to 3 MB


@router.get("/whatsapp", response_class=PlainTextResponse)
async def verify_subscription(
    settings: SettingsDep,
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> str:
    echoed = verify_challenge(settings.whatsapp_verify_token, mode, token, challenge)
    if echoed is None:
        raise ForbiddenError("Verification failed")
    return echoed


@router.post("/whatsapp")
async def receive(request: Request, session: SessionDep, settings: SettingsDep) -> dict[str, bool]:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise FileRejectedError("Payload too large")
    if not verify_signature(
        settings.whatsapp_app_secret, raw, request.headers.get("X-Hub-Signature-256")
    ):
        log.warning("whatsapp_bad_signature")
        # Meta never sends a bad signature, so only a prober does: shut that address out quickly.
        if settings.rate_limit_enabled:
            wait = request.app.state.limiter.hit(
                f"bad-signature:{client_ip(request, settings)}", 20, 60
            )
            if wait is not None:
                raise RateLimitedError(wait)
        raise ForbiddenError("Invalid signature")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise FileRejectedError("Invalid payload") from exc
    messages, statuses = parse_webhook(payload)
    await InboundService(session, settings).receive(messages, statuses)
    return {"ok": True}
