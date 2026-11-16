import uuid

from app.agents.base import BaseAgent
from app.agents.models import (
    MappingInput,
    MappingOutput,
    RequirementsInput,
    RequirementsOutput,
    Turn,
)
from app.core.context import TenantContext
from app.llm.prompting import sanitize_customer_text


class QuoteAgent(BaseAgent):
    """Collects what a customer needs, then matches it to catalogue items.

    It proposes WHICH items and how many. It never creates a quote and never produces a price:
    the orchestrator validates what it says and the pricing engine does all the arithmetic.
    """

    name = "quote"
    template = "quote_requirements"
    slot = "large"
    tools = frozenset({"lookup_catalog"})  # read-only; cannot create or change a quote

    async def collect(
        self,
        ctx: TenantContext,
        data: RequirementsInput,
        *,
        message_id: uuid.UUID | None = None,
    ) -> RequirementsOutput:
        turns = [Turn(role=t.role, text=sanitize_customer_text(t.text)) for t in data.turns]
        return await self.invoke(
            ctx,
            RequirementsOutput,
            data,
            message_id=message_id,
            template="quote_requirements",
            categories=data.categories,
            category=data.category,
            filled=data.filled,
            turns=turns,
        )

    async def propose(
        self, ctx: TenantContext, data: MappingInput, *, message_id: uuid.UUID | None = None
    ) -> MappingOutput:
        return await self.invoke(
            ctx,
            MappingOutput,
            data,
            message_id=message_id,
            template="quote_mapping",
            category=data.category,
            requirements={k: sanitize_customer_text(str(v)) for k, v in data.requirements.items()},
            candidates=data.candidates,
        )
