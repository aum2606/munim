import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import Config, Context, Owner, Session
from app.core.inbox import InboxService
from app.core.tenant import TenantContext
from app.repositories.conversations import ConversationRepository
from app.repositories.followups import FollowupRepository
from app.repositories.identity import TenantRepository
from app.repositories.inbox import InboxRepository
from app.schemas.chat import ConversationView, MessageView
from app.schemas.leads import (
    BusinessHours,
    DraftView,
    FollowupView,
    HandoffView,
    ModeChange,
    StaffReply,
)

router = APIRouter()


async def inbox_events(
    sessions: async_sessionmaker[AsyncSession], ctx: TenantContext, once: bool
) -> AsyncIterator[str]:
    import json

    for _ in range(30):
        async with sessions() as session:
            payload = {
                "conversations": [
                    ConversationView.model_validate(entry).model_dump(mode="json")
                    for entry in await ConversationRepository(session, ctx).filtered()
                ],
                "handoffs": [
                    HandoffView.model_validate(entry).model_dump(mode="json")
                    for entry in await InboxRepository(session, ctx).handoffs()
                ],
                "followups": [
                    FollowupView.model_validate(entry).model_dump(mode="json")
                    for entry in await FollowupRepository(session, ctx).pending()
                ],
            }
        # Each tick also invalidates the selected conversation's private drafts/messages.
        yield "event: inbox\ndata: " + json.dumps(payload) + "\n\n"
        if once:
            return
        await asyncio.sleep(2)


@router.get("/conversations/stream")
async def stream(
    request: Request, session: Session, ctx: Context, once: bool = False
) -> StreamingResponse:
    await session.rollback()
    return StreamingResponse(
        inbox_events(request.app.state.sessions, ctx, once),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/conversations/{conversation_id}/mode", status_code=204)
async def mode(
    conversation_id: UUID, body: ModeChange, session: Session, ctx: Context, config: Config
) -> None:
    await InboxService(session, ctx, config).mode(conversation_id, body.mode)


@router.post(
    "/conversations/{conversation_id}/messages", response_model=MessageView, status_code=201
)
async def reply(
    conversation_id: UUID, body: StaffReply, session: Session, ctx: Context, config: Config
) -> MessageView:
    message = await InboxService(session, ctx, config).reply(
        conversation_id,
        body.content,
        body.external_id,
        [button.model_dump() for button in body.buttons],
    )
    await session.commit()
    return MessageView.model_validate(message)


@router.get("/conversations/{conversation_id}/drafts", response_model=list[DraftView])
async def drafts(conversation_id: UUID, session: Session, ctx: Context) -> list[DraftView]:
    await ConversationRepository(session, ctx).get(conversation_id)
    return [
        DraftView.model_validate(entry)
        for entry in await InboxRepository(session, ctx).drafts(conversation_id)
    ]


@router.post("/reply-drafts/{draft_id}/approve", response_model=MessageView)
async def approve(draft_id: UUID, session: Session, ctx: Context, config: Config) -> MessageView:
    return MessageView.model_validate(
        await InboxService(session, ctx, config).approve_draft(draft_id)
    )


@router.get("/handoffs", response_model=list[HandoffView])
async def handoffs(session: Session, ctx: Context) -> list[HandoffView]:
    return [
        HandoffView.model_validate(entry)
        for entry in await InboxRepository(session, ctx).handoffs()
    ]


@router.get("/tenant/business-hours", response_model=BusinessHours)
async def hours(session: Session, ctx: Context) -> BusinessHours:
    return BusinessHours(hours=(await TenantRepository(session, ctx).settings()).business_hours)


@router.put("/tenant/business-hours", response_model=BusinessHours)
async def save_hours(body: BusinessHours, session: Session, ctx: Owner) -> BusinessHours:
    settings = await TenantRepository(session, ctx).settings()
    settings.business_hours = body.hours
    await session.commit()
    return body
