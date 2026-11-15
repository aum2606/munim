import uuid

from app.agents.base import BaseAgent
from app.agents.models import RouterInput, RouterOutput
from app.core.context import TenantContext
from app.llm.prompting import sanitize_customer_text


class RouterAgent(BaseAgent):
    name = "router"
    template = "router"
    slot = "small"
    tools = frozenset()  # classifies only; no tools

    async def run(
        self, ctx: TenantContext, data: RouterInput, *, message_id: uuid.UUID | None = None
    ) -> RouterOutput:
        clean = data.model_copy(
            update={
                "turns": [
                    t.model_copy(update={"text": sanitize_customer_text(t.text)})
                    for t in data.turns
                ]
            }
        )
        return await self.invoke(
            ctx,
            RouterOutput,
            data,
            message_id=message_id,
            business_type=clean.business_type,
            turns=clean.turns,
            quote_flow_active=clean.quote_flow_active,
        )
