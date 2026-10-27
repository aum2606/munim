from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from app.core.credentials import decrypt_credential, encrypt_credential
from app.core.errors import DomainError, NotFound
from app.db.models import ChannelDelivery, Message, WhatsAppContact, WhatsAppTemplate
from app.repositories.channels import ChannelRepository, due_deliveries
from app.repositories.scoped import ScopedRepository
from tests.integration.test_workspace import owner


async def test_encrypted_accounts_inbound_replay_and_resource_isolation(client, sessions):
    _, ctx, _ = await owner(client)
    _, other, _ = await owner(client)
    key = SecretStr(Fernet.generate_key().decode())
    encrypted = encrypt_credential(key, SecretStr("synthetic-provider-credential"))
    assert "synthetic-provider-credential" not in encrypted
    assert decrypt_credential(key, encrypted) == "synthetic-provider-credential"
    with pytest.raises(DomainError):
        decrypt_credential(SecretStr(Fernet.generate_key().decode()), encrypted)
    with pytest.raises(DomainError):
        encrypt_credential(SecretStr(""), SecretStr("synthetic"))
    async with sessions() as session:
        repo = ChannelRepository(session, ctx)
        account = await repo.create(
            external_id=str(uuid4().int),
            business_account_id="synthetic",
            credentials_encrypted=encrypted,
        )
        when = datetime.now(UTC) - timedelta(hours=25)
        message = await repo.inbound(
            account, "919000000001", "wamid.synthetic", "Hello", when, "text", []
        )
        contact = await repo.contact(message.conversation_id)
        from app.repositories.conversations import ConversationRepository

        conversation = await ConversationRepository(session, ctx).get(message.conversation_id)
        assert conversation.last_customer_msg_at == when
        conversation.status = "closed"
        replay = await repo.inbound(
            account, "919000000001", "wamid.synthetic", "Hello", when, "text", []
        )
        assert replay.id == message.id and conversation.status == "closed"
        template = await ScopedRepository(session, ctx, WhatsAppTemplate).create(
            account_id=account.id,
            name="demo",
            language="en",
            provider_id="synthetic",
            status="APPROVED",
            body_text="Can we help?",
            usable=True,
        )
        # Queue against an open conversation; outbound message created by actual services later.
        conversation.status = "open"
        outbound = await ScopedRepository(session, ctx, Message).create(
            conversation_id=conversation.id, direction="out", sender_type="ai", content="Hello"
        )
        delivery = await repo.queue(outbound)
        assert delivery is not None
        for model, resource in [
            (WhatsAppContact, contact),
            (WhatsAppTemplate, template),
            (ChannelDelivery, delivery),
        ]:
            with pytest.raises(NotFound):
                await ScopedRepository(session, other, model).get(resource.id, for_update=True)
            assert await ScopedRepository(session, other, model).list() == []
        with pytest.raises(NotFound):
            await ChannelRepository(session, other).get(account.id)
        assert await due_deliveries(session, other, datetime.now(UTC)) == []
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await ScopedRepository(session, other, WhatsAppTemplate).create(
                    account_id=account.id,
                    name="bad",
                    language="en",
                    provider_id="bad",
                    status="APPROVED",
                    body_text="Invalid cross tenant",
                )
        await session.commit()
