from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models import Conversation, Message, ReplyDraft
from app.db.models.conversation import ConversationMode, ConversationStatus, Direction, SenderType
from app.repositories.scoped import ScopedRepository


class ConversationRepository(ScopedRepository[Conversation]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, Conversation)

    async def filtered(
        self,
        status: ConversationStatus | None = None,
        mode: ConversationMode | None = None,
        channel: str | None = None,
        q: str | None = None,
    ) -> list[Conversation]:
        statement = select(Conversation).where(Conversation.tenant_id == self.ctx.tenant_id)
        if status:
            statement = statement.where(Conversation.status == status)
        if mode:
            statement = statement.where(Conversation.mode == mode)
        if channel:
            statement = statement.where(Conversation.channel == channel)
        if q:
            statement = statement.where(
                select(Message.id)
                .where(
                    Message.tenant_id == self.ctx.tenant_id,
                    Message.conversation_id == Conversation.id,
                    Message.content.icontains(q, autoescape=True),
                )
                .exists()
            )
        return list(
            await self.session.scalars(
                statement.order_by(Conversation.updated_at.desc()).limit(100)
            )
        )

    async def messages(self, conversation_id: UUID, limit: int = 100) -> list[Message]:
        await self.get(conversation_id)
        result = list(
            await self.session.scalars(
                select(Message)
                .where(
                    Message.tenant_id == self.ctx.tenant_id,
                    Message.conversation_id == conversation_id,
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit)
            )
        )
        return list(reversed(result))

    async def pending(self, conversation_id: UUID) -> list[Message]:
        await self.get(conversation_id)
        return list(
            await self.session.scalars(
                select(Message)
                .where(
                    Message.tenant_id == self.ctx.tenant_id,
                    Message.conversation_id == conversation_id,
                    Message.direction == Direction.IN,
                    Message.processed_at.is_(None),
                )
                .order_by(Message.created_at, Message.id)
                .limit(50)
            )
        )

    async def receive(self, conversation_id: UUID, content: str, external_id: str) -> Message:
        conversation = await self.get(conversation_id, for_update=True)
        statement = (
            insert(Message)
            .values(
                tenant_id=self.ctx.tenant_id,
                conversation_id=conversation_id,
                content=content,
                external_id=external_id,
                direction=Direction.IN,
                sender_type=SenderType.CUSTOMER,
                content_type="text",
                attachments=[],
            )
            .on_conflict_do_nothing(
                index_elements=[Message.tenant_id, Message.conversation_id, Message.external_id]
            )
            .returning(Message)
        )
        message = (await self.session.scalars(statement)).one_or_none()
        if message is None:
            message = (
                await self.session.scalars(
                    select(Message).where(
                        Message.tenant_id == self.ctx.tenant_id,
                        Message.conversation_id == conversation_id,
                        Message.external_id == external_id,
                    )
                )
            ).one()
            if message.content != content:
                raise DomainError("Message ID already used for different content", 409)
        else:
            conversation.last_customer_msg_at = datetime.now(UTC)
        await self.session.flush()
        return message

    async def finish(
        self,
        conversation_id: UUID,
        pending: list[Message],
        text: str | None,
        *,
        intent: str,
        language: str,
        agent_run_id: UUID | None = None,
        citations: list[str] | None = None,
        handoff: bool = False,
    ) -> Message | None:
        conversation = await self.get(conversation_id, for_update=True)
        current = await self.pending(conversation_id)
        pending_ids = {message.id for message in current}
        if not pending or pending[-1].id not in pending_ids:
            return None
        if handoff:
            conversation.mode = ConversationMode.HUMAN
        now = datetime.now(UTC)
        for message in pending:
            if message.id in pending_ids:
                message.processed_at = now
                message.intent = intent
                message.language = language
        if conversation.status != ConversationStatus.OPEN or (
            conversation.mode == ConversationMode.HUMAN and not handoff
        ):
            text = None
        if text is not None and conversation.mode == ConversationMode.ASSIST:
            self.session.add(
                ReplyDraft(
                    tenant_id=self.ctx.tenant_id,
                    conversation_id=conversation_id,
                    source_message_id=pending[-1].id,
                    content=text,
                )
            )
            await self.session.flush()
            return None
        if text is None:
            await self.session.flush()
            return None
        outbound = Message(
            tenant_id=self.ctx.tenant_id,
            conversation_id=conversation_id,
            direction=Direction.OUT,
            sender_type=SenderType.AI,
            content=text,
            in_reply_to_id=pending[-1].id,
            language=language,
            intent=intent,
            agent_run_id=agent_run_id,
            attachments=[{"citations": citations or []}],
        )
        self.session.add(outbound)
        conversation.last_business_msg_at = now
        await self.session.flush()
        return outbound
