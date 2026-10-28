import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.errors import NotFound, Unauthorized
from app.core.privacy import PrivacyService
from app.core.security import token_hash
from app.db.models import AgentRun, Conversation, Customer, Message, Quote, Role, WidgetSession
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.identity import TenantRepository, UserRepository
from app.repositories.scoped import ScopedRepository
from app.repositories.widget import WidgetCredentialRepository
from app.schemas.privacy import NOTICE_VERSION
from tests.integration.test_analytics import seed_analytics
from tests.integration.test_workspace import owner


async def test_public_widget_requires_current_explicit_consent(client, sessions, redis_url):
    _, ctx, _ = await owner(client)
    async with sessions() as session:
        key = (await TenantRepository(session, ctx).get()).widget_public_key
    assert (await client.post("/api/v1/widget/session", json={"key": key})).status_code == 409
    assert (
        await client.post(
            "/api/v1/widget/session", json={"key": key, "consent": True, "notice_version": "old"}
        )
    ).status_code == 409
    created = await client.post(
        "/api/v1/widget/session",
        json={"key": key, "consent": True, "notice_version": NOTICE_VERSION},
    )
    assert created.status_code == 201
    async with sessions() as session:
        widget = await ScopedRepository(session, ctx, WidgetSession).get(
            UUID(created.json()["session_id"])
        )
        assert widget.consented_at and not widget.is_playground
        widget.notice_version = "old"
        await session.commit()
        with pytest.raises(Unauthorized):
            await WidgetCredentialRepository(session).authenticate(
                token_hash(created.json()["token"])
            )


async def test_erasure_deletes_graph_all_pdf_versions_and_isolates_tenants(
    client, sessions, tmp_path
):
    a, ctx, _ = await owner(client)
    b, other, _ = await owner(client)
    client._transport.app.state.settings.storage_dir = str(tmp_path)
    async with sessions() as session:
        records, _ = await seed_analytics(session, ctx, datetime.now(UTC))
        await seed_analytics(session, other, datetime.now(UTC))
        conversation, lead, message = records[0]
        customer_id, conversation_id, message_id = (
            conversation.customer_id,
            conversation.id,
            message.id,
        )
        quote = await session.scalar(
            select(Quote).where(
                Quote.tenant_id == ctx.tenant_id, Quote.conversation_id == conversation_id
            )
        )
        files = [
            tmp_path / str(ctx.tenant_id) / "quotes" / f"{quote.id}-v{version}-sent.pdf"
            for version in (1, 2)
        ]

        def create_files():
            files[0].parent.mkdir(parents=True, exist_ok=True)
            for path in files:
                path.write_bytes(b"%PDF-synthetic")

        await asyncio.to_thread(create_files)
    body = {"confirm_customer_id": str(customer_id), "retention_reviewed": True}
    assert (
        await client.request("DELETE", f"/api/v1/customers/{customer_id}", json=body)
    ).status_code == 401
    assert (
        await client.request("DELETE", f"/api/v1/customers/{customer_id}", headers=b, json=body)
    ).status_code == 404
    erased = await client.request(
        "DELETE", f"/api/v1/customers/{customer_id}", headers=a, json=body
    )
    assert erased.status_code == 200, erased.text
    assert erased.json()["status"] == "complete"
    assert all(
        not exists for exists in await asyncio.to_thread(lambda: [path.exists() for path in files])
    )
    repeated = await client.request(
        "DELETE", f"/api/v1/customers/{customer_id}", headers=a, json=body
    )
    assert repeated.json()["id"] == erased.json()["id"]
    assert (
        await client.post(f"/api/v1/privacy/erasures/{erased.json()['id']}/retry", headers=b)
    ).status_code == 404
    async with sessions() as session:
        for model, resource in [
            (Customer, customer_id),
            (Conversation, conversation_id),
            (Message, message_id),
        ]:
            with pytest.raises(NotFound):
                await ScopedRepository(session, ctx, model).get(resource)
        assert len(await ScopedRepository(session, other, Customer).list()) == 7
        # Late model completions retain audit metadata without restoring erased prompts or FKs.
        await DatabaseRunRecorder(sessions).record(
            ctx,
            agent="router",
            model="fake",
            request={"private": "erased customer name"},
            output={"private": "must disappear"},
            tool_calls=[],
            latency_ms=100,
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd_micros=0,
            status="success",
            error=None,
            message_id=message_id,
            started_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        runs = list(
            await session.scalars(select(AgentRun).where(AgentRun.tenant_id == ctx.tenant_id))
        )
        assert runs and all(run.input == {"privacy_erased": True} for run in runs)
        assert all(run.message_id is None and not run.output for run in runs)


async def test_erasure_requires_owner_and_matching_confirmation_and_private_file_paths(
    client, sessions, tmp_path
):
    headers, ctx, user_id = await owner(client)
    config = client._transport.app.state.settings
    config.storage_dir = str(tmp_path)
    async with sessions() as session:
        customer = await ScopedRepository(session, ctx, Customer).create(name="Synthetic")
        customer_id = customer.id
        await session.commit()
    path = f"/api/v1/customers/{customer_id}"
    assert (
        await client.request(
            "DELETE", path, headers=headers, json={"confirm_customer_id": str(customer_id)}
        )
    ).status_code == 422
    assert (
        await client.request(
            "DELETE",
            path,
            headers=headers,
            json={"confirm_customer_id": str(uuid4()), "retention_reviewed": True},
        )
    ).status_code == 409
    async with sessions() as session:
        user = await UserRepository(session, ctx).get(user_id)
        user.role = Role.STAFF
        await session.commit()
    assert (
        await client.request(
            "DELETE",
            path,
            headers=headers,
            json={"confirm_customer_id": str(customer_id), "retention_reviewed": True},
        )
    ).status_code == 403
    async with sessions() as session:
        service = PrivacyService(session, ctx, config)
        record = await service.repository.erase(customer_id)
        record.files = [str(tmp_path / "outside-tenant.txt")]
        await session.commit()
        result = await service.finish_files(record.id)
        assert result.status == "pending_files" and result.files_remaining == 1


async def test_whatsapp_erasure_tombstone_blocks_old_signed_replay(client, sessions):
    from app.db.models import ChannelDelivery, WhatsAppContact
    from app.db.models.channel import DeliveryStatus
    from app.db.models.conversation import Direction, SenderType
    from app.repositories.channels import ChannelRepository
    from tests.integration.test_whatsapp_webhooks import inbound, setup_channel, signed

    auth, ctx, _, account = await setup_channel(client)
    raw, signature = signed(inbound(phone_id=account["external_id"]))
    assert (
        await client.post("/api/v1/webhooks/whatsapp", content=raw, headers=signature)
    ).status_code == 200
    async with sessions() as session:
        contact = (await ScopedRepository(session, ctx, WhatsAppContact).list())[0]
        customer_id = contact.customer_id
        outbound = await ScopedRepository(session, ctx, Message).create(
            conversation_id=contact.conversation_id,
            direction=Direction.OUT,
            sender_type=SenderType.STAFF,
            content="Synthetic reply",
        )
        delivery = await ChannelRepository(session, ctx).queue(outbound)
        delivery.status = DeliveryStatus.UNCERTAIN
        delivery_id = delivery.id
        await session.commit()
    body = {"confirm_customer_id": str(customer_id), "retention_reviewed": True}
    assert (
        await client.request("DELETE", f"/api/v1/customers/{customer_id}", headers=auth, json=body)
    ).status_code == 409
    async with sessions() as session:
        delivery = await ScopedRepository(session, ctx, ChannelDelivery).get(delivery_id)
        delivery.status = DeliveryStatus.FAILED
        await session.commit()
    response = await client.request(
        "DELETE", f"/api/v1/customers/{customer_id}", headers=auth, json=body
    )
    assert response.status_code == 200, response.text
    assert (
        await client.post("/api/v1/webhooks/whatsapp", content=raw, headers=signature)
    ).status_code == 200
    async with sessions() as session:
        assert not await ScopedRepository(session, ctx, Customer).list()
        assert not await ScopedRepository(session, ctx, Message).list()
