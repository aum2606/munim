import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.security import issue_token
from app.llm import FakeEmbedder, FakeLLM
from app.llm.offline import agent_response
from app.orchestrator.requirements import RequirementsFlow
from app.quotes.service import QuoteService
from app.repositories.conversations import ConversationRepository
from app.repositories.identity import UserRepository
from app.repositories.quotes import QuoteRepository
from seeds.demo import seed_demo
from tests.integration.test_workspace import owner
from tests.unit.test_agents import MemoryRecorder


async def setup_quote(client, sessions, tmp_path, finishing="none"):
    app = client._transport.app
    app.state.settings.storage_dir = str(tmp_path)
    ctx = (await seed_demo(sessions, FakeEmbedder(), "unused-hash"))["printing"]
    async with sessions() as session:
        user = (await UserRepository(session, ctx).list())[0]
        token, _ = issue_token(app.state.settings, user.id, ctx.tenant_id, "access")
    auth = {"Authorization": "Bearer " + token}
    assert (
        await client.put(
            "/api/v1/tenant/quote-profile",
            headers=auth,
            json={
                "name": "Demo Printing",
                "gstin": "24AAAAA0000A1Z5",
                "state_code": "24",
                "address": "Demo market",
            },
        )
    ).status_code == 200
    widget = (await client.post("/api/v1/playground/session", headers=auth)).json()
    fake = FakeLLM(MemoryRecorder(), {}, fallback=agent_response)
    async with sessions() as session:
        conversation_id = UUID(widget["conversation_id"])
        message = await ConversationRepository(session, ctx).receive(
            conversation_id, "quote", str(uuid4())
        )
        await RequirementsFlow(session, ctx, fake).collect(
            conversation_id,
            message.id,
            "item=visiting cards; quantity=500; sides=double-sided; size=standard; "
            f"material=standard; colour=colour; finishing={finishing}; deadline=2026-12-20",
            "printing",
        )
        quote = await QuoteService(session, ctx, app.state.settings).create_from_requirements(
            conversation_id, message.id, fake
        )
        quote_id = str(quote.id)
        await session.commit()
    return auth, ctx, user.id, widget, quote_id


async def test_owner_edits_recalculate_version_check_and_concurrent_send_is_idempotent(
    client, sessions, tmp_path
):
    auth, ctx, user_id, widget, quote_id = await setup_quote(client, sessions, tmp_path)
    other, _, _ = await owner(client)
    path = "/api/v1/quotes/" + quote_id
    original = (await client.get(path, headers=auth)).json()
    edit = {
        "expected_version": 1,
        "customer_state": "27",
        "lines": [{"sku": "CARD-100", "qty": "6", "options": original["lines"][0]["options"]}],
    }
    assert (await client.patch(path, json=edit)).status_code == 401
    assert (await client.patch(path, headers=other, json=edit)).status_code == 404
    bad = {**edit, "lines": [{"sku": "CARD-100", "qty": "0"}]}
    assert (await client.patch(path, headers=auth, json=bad)).status_code == 422
    revised = await client.patch(path, headers=auth, json=edit)
    assert revised.status_code == 200, revised.text
    assert revised.json()["version"] == 2 and revised.json()["totals"]["total_paise"] == 389400
    assert (
        revised.json()["totals"]["igst_paise"] == 59400
        and revised.json()["totals"]["cgst_paise"] == 0
    )
    assert (await client.patch(path, headers=auth, json=edit)).status_code == 409
    assert (
        await client.post(path + "/approve", headers=auth, json={"expected_version": 1})
    ).status_code == 409
    responses = await asyncio.gather(
        *(
            client.post(path + "/approve", headers=auth, json={"expected_version": 2})
            for _ in range(2)
        )
    )
    assert all(response.status_code == 200 for response in responses)
    history = (
        await client.get(
            "/api/v1/conversations/" + widget["conversation_id"] + "/messages", headers=auth
        )
    ).json()
    assert (
        sum(
            any(attachment.get("quote_id") == quote_id for attachment in message["attachments"])
            for message in history
        )
        == 1
    )
    assert (
        await client.patch(path, headers=auth, json={**edit, "expected_version": 2})
    ).status_code == 409
    assert (
        await client.post(path + "/mark-accepted", headers=auth, json={"expected_version": 2})
    ).status_code == 200
    async with sessions() as session:
        from app.db.models.user import Role

        user = await UserRepository(session, ctx).get(user_id)
        user.role = Role.STAFF
        await session.commit()
    try:
        assert (
            await client.post(path + "/approve", headers=auth, json={"expected_version": 2})
        ).status_code == 403
        await seed_demo(sessions, FakeEmbedder(), "unused-hash")
        async with sessions() as session:
            assert (await UserRepository(session, ctx).get(user_id)).role == Role.STAFF
    finally:
        async with sessions() as session:
            (await UserRepository(session, ctx).get(user_id)).role = Role.OWNER
            await session.commit()


async def test_unpriced_expired_and_invalid_profile_settings_are_blocked(
    client, sessions, tmp_path
):
    auth, ctx, _, _, quote_id = await setup_quote(client, sessions, tmp_path, finishing="foil")
    path = "/api/v1/quotes/" + quote_id
    assert (
        await client.post(path + "/approve", headers=auth, json={"expected_version": 1})
    ).status_code == 409
    assert (
        await client.put(
            "/api/v1/tenant/settings", headers=auth, json={"auto_send_limit_inr": "-1"}
        )
    ).status_code == 422
    assert (
        await client.put("/api/v1/tenant/settings", headers=auth, json={"auto_send_limit_inr": 123})
    ).status_code == 422
    assert (
        await client.put(
            "/api/v1/tenant/quote-profile",
            headers=auth,
            json={"name": "Demo", "gstin": "24AAAAA0000A1Z5", "state_code": "27"},
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/v1/tenant/logo", headers=auth, files={"file": ("logo.png", b"not an image")}
        )
    ).status_code == 400
    async with sessions() as session:
        quote = await QuoteRepository(session, ctx).get(UUID(quote_id))
        quote.valid_until = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert (
        await client.post(path + "/approve", headers=auth, json={"expected_version": 1})
    ).status_code == 409
