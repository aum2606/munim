import uuid

from app.agents.base import BaseAgent
from app.agents.models import ResponderInput, ResponderOutput
from app.core.context import TenantContext


class ResponderAgent(BaseAgent):
    """Turns verified answer points and code-built price lines into a chat message. It has no
    tools: it can only rephrase what it is given, and guardrails check what it writes."""

    name = "responder"
    template = "responder"
    slot = "small"
    tools = frozenset()

    async def run(
        self, ctx: TenantContext, data: ResponderInput, *, message_id: uuid.UUID | None = None
    ) -> str:
        output = await self.invoke(
            ctx,
            ResponderOutput,
            data,
            message_id=message_id,
            channel=data.channel,
            language=data.language,
            script=data.script,
            tone=data.tone,
            max_chars=data.max_chars,
            answer_points=data.answer_points,
            price_lines=data.price_lines,
            violation_feedback=data.violation_feedback,
        )
        return output.reply.strip()
