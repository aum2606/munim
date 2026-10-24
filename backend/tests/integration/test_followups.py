from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.followups import FollowupService
from app.db.models import Conversation
from app.repositories.conversations import ConversationRepository
from app.repositories.followups import FollowupRepository
from app.repositories.leads import LeadRepository
from app.repositories.scoped import ScopedRepository
from tests.integration.test_quote_approval import setup_quote
from tests.integration.test_workspace import owner


async def test_quote_reminder_and_disabled_policy(client, sessions, tmp_path):
    auth, ctx, _, widget, quote_id = await setup_quote(client, sessions, tmp_path)
    from app.db.models.quote import QuoteStatus
    from app.repositories.quotes import QuoteRepository

    now = datetime.now(UTC)
    async with sessions() as session:
        quote = await QuoteRepository(session, ctx).get(UUID(quote_id))
        quote.status, quote.sent_at = QuoteStatus.SENT, now - timedelta(days=1)
        quote.valid_until = now + timedelta(hours=12)
        conversation = await ConversationRepository(session, ctx).get(
            UUID(widget["conversation_id"])
        )
        conversation.last_business_msg_at = now - timedelta(days=1)
        conversation.last_customer_msg_at = now - timedelta(days=2)
        await session.commit()
        service = FollowupService(session, ctx)
        await service.schedule(now)
        pending = await FollowupRepository(session, ctx).pending()
        assert any(
            draft.kind == "quote_reminder" and draft.lead_id == quote.lead_id for draft in pending
        )
    assert (
        await client.put("/api/v1/tenant/followup-policy", headers=auth, json={"enabled": False})
    ).status_code == 200
    try:
        async with sessions() as session:
            await FollowupService(session, ctx).schedule(now)
            assert await FollowupRepository(session, ctx).pending() == []
    finally:
        await client.put("/api/v1/tenant/followup-policy", headers=auth, json={})


async def test_due_drafts_idempotency_owner_approval_and_stale_reply(client, sessions):
    a, ctx, _ = await owner(client)
    b, _, _ = await owner(client)
    assert (await client.get("/api/v1/followups")).status_code == 401
    assert (
        await client.put("/api/v1/tenant/followup-policy", headers=a, json={"no_reply_days": 0})
    ).status_code == 422
    widget = (await client.post("/api/v1/playground/session", headers=a)).json()
    conversation_id = UUID(widget["conversation_id"])
    now = datetime.now(UTC)
    async with sessions() as session:
        conversation = await ScopedRepository(session, ctx, Conversation).get(conversation_id)
        conversation.last_customer_msg_at = now - timedelta(days=4)
        conversation.last_business_msg_at = now - timedelta(days=3)
        lead = await LeadRepository(session, ctx).for_conversation(conversation_id, "printing")
        lead.stage_override = True
        lead.next_followup_at = now + timedelta(days=5)
        await session.commit()
        service = FollowupService(session, ctx)
        await service.schedule(now)
        assert await FollowupRepository(session, ctx).pending() == []
        lead.next_followup_at = None
        await session.commit()
        await service.schedule(now)
        await service.schedule(now)
        drafts = await FollowupRepository(session, ctx).pending()
        assert len(drafts) == 1 and drafts[0].kind == "no_reply"
        draft_id = drafts[0].id
        assert await ConversationRepository(session, ctx).messages(conversation_id) == []
    path = f"/api/v1/followups/{draft_id}/action"
    assert (await client.post(path, headers=b, json={"action": "approve"})).status_code == 404
    assert (await client.get("/api/v1/followups", headers=b)).json() == []
    sent = await client.post(path, headers=a, json={"action": "approve"})
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    assert (await client.post(path, headers=a, json={"action": "approve"})).json()[
        "status"
    ] == "sent"
    async with sessions() as session:
        messages = await ConversationRepository(session, ctx).messages(conversation_id)
        assert len(messages) == 1 and messages[0].sender_type == "staff"
        conversation = await ConversationRepository(session, ctx).get(conversation_id)
        conversation.last_business_msg_at = now - timedelta(days=20)
        conversation.last_customer_msg_at = now - timedelta(days=21)
        await session.commit()
        await FollowupService(session, ctx).schedule(now)
        drafts = await FollowupRepository(session, ctx).pending()
        assert len(drafts) == 1 and drafts[0].kind == "reengage"
        stale_id = drafts[0].id
        await ConversationRepository(session, ctx).receive(conversation_id, "I have replied", "new")
        await session.commit()
    stale = await client.post(
        f"/api/v1/followups/{stale_id}/action", headers=a, json={"action": "approve"}
    )
    assert stale.status_code == 200 and stale.json()["status"] == "skipped"
    async with sessions() as session:
        assert len(await ConversationRepository(session, ctx).messages(conversation_id)) == 2
