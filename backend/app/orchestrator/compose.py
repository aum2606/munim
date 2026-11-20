from collections.abc import Collection

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contacts import Contact, allowed_contacts
from app.agents.guardrails import check_reply
from app.agents.models import ResponderInput, RouterOutput
from app.agents.responder import ResponderAgent
from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import Conversation, ConversationMode, Message
from app.db.session import SessionMaker
from app.llm.base import LLMClient
from app.orchestrator.messages import canned
from app.repositories.tenant import TenantRepository

log = structlog.get_logger()

MAX_CHARS = {"playground": 1500, "whatsapp": 1000}
MAX_REGENERATIONS = 1  # one retry with the violation fed back, then hand off


async def compose_reply(
    llm: LLMClient,
    sessionmaker: SessionMaker,
    settings: Settings,
    ctx: TenantContext,
    session: AsyncSession,
    conversation: Conversation,
    router: RouterOutput,
    trigger: Message,
    *,
    answer_points: list[str],
    price_lines: list[str],
    allowed_paise: Collection[int],
    evidence_contacts: Collection[Contact] = (),
) -> str:
    """Have the Responder write the reply, and check it. Any amount in it must be in
    allowed_paise. One regeneration on a violation; after that nothing is sent and a person
    takes over."""
    tenants = TenantRepository(session, ctx)
    tenant_settings = await tenants.get_settings()
    tenant = await tenants.get()
    # The only contacts a reply may repeat: the shop's own phone and what its data says this turn.
    contacts = allowed_contacts(tenant.phone if tenant else None) | frozenset(evidence_contacts)
    channel = conversation.channel.value
    limit = MAX_CHARS.get(channel, 1000)
    responder = ResponderAgent(llm, sessionmaker)
    feedback: str | None = None
    for _ in range(MAX_REGENERATIONS + 1):
        reply = await responder.run(
            ctx,
            ResponderInput(
                language=router.language,
                script=router.script,
                tone=tenant_settings.tone if tenant_settings else "friendly",
                channel=channel,
                max_chars=limit,
                answer_points=answer_points,
                price_lines=price_lines,
                violation_feedback=feedback,
            ),
            message_id=trigger.id,
        )
        violations = check_reply(reply, allowed_paise, limit, allowed_contacts=contacts)
        if not violations:
            return reply
        log.warning("guardrail_blocked", rules=[v.rule for v in violations])
        feedback = "; ".join(v.detail for v in violations)
    conversation.mode = ConversationMode.HUMAN
    return canned("handoff", router.language)
