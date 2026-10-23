from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.requirements import RequirementsAgent
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models.lead import LeadStage
from app.llm import LLMClient
from app.repositories.conversations import ConversationRepository
from app.repositories.leads import LeadRepository
from app.repositories.requirements import RequirementRepository
from app.schemas.requirements import Category, RequirementsInput, SlotUpdate, value_valid


def category_for(business_type: str) -> Category:
    text = business_type.lower()
    for term, category in (
        ("photo", "photography"),
        ("print", "printing"),
        ("interior", "interior"),
        ("repair", "repair"),
        ("electronic", "electronics"),
    ):
        if term in text:
            return cast(Category, category)
    raise DomainError("The team needs to set up requirements for this business")


class RequirementsFlow:
    def __init__(self, session: AsyncSession, ctx: TenantContext, llm: LLMClient) -> None:
        self.session, self.ctx, self.llm = session, ctx, llm

    async def collect(
        self, conversation_id: UUID, message_id: UUID, question: str, business_type: str
    ) -> tuple[dict[str, Any], str]:
        conversations = ConversationRepository(self.session, self.ctx)
        conversation = await conversations.get(conversation_id, for_update=True)
        previous = conversation.active_flow
        category = category_for(previous.get("category", business_type))
        schema = await RequirementRepository(self.session, self.ctx).for_category(category)
        properties = schema.json_schema["properties"]
        filled = {
            key: value
            for key, value in previous.get("filled", {}).items()
            if key in properties and value_valid(value, properties[key])
        }
        result = await RequirementsAgent(self.llm).run(
            self.ctx,
            RequirementsInput(
                question=question,
                category=category,
                slots=list(properties),
                awaiting=previous.get("awaiting", []),
                filled=[SlotUpdate(key=key, value=str(value)) for key, value in filled.items()],
            ),
            message_id=message_id,
        )
        for update in result.updates:
            if update.key not in properties:
                raise DomainError("Unknown requirement slot")
            spec = properties[update.key]
            value: Any = update.value.strip()
            if value.lower() in {"unknown", "don't know", "dont know", "pata nahi"}:
                if update.key not in schema.defaults:
                    continue
                value = schema.defaults[update.key]
            elif spec["type"] == "integer":
                if not value.isdecimal():
                    raise DomainError("Requirement must be a whole number")
                value = int(value)
            elif spec["type"] == "boolean":
                if value.lower() not in {"true", "false", "yes", "no"}:
                    raise DomainError("Requirement must be yes or no")
                value = value.lower() in {"true", "yes"}
            if not value_valid(value, spec):
                raise DomainError("Requirement does not match the service schema")
            filled[update.key] = value
        missing = [key for key in schema.json_schema.get("required", []) if key not in filled]
        state = {
            "kind": "quote",
            "category": category,
            "filled": filled,
            "missing": missing,
            "awaiting": missing[:2],
            "ready_for_quote": not missing,
        }
        conversation.active_flow = state
        lead = await LeadRepository(self.session, self.ctx).for_conversation(
            conversation_id, category
        )
        lead.requirements = dict(filled)
        lead.stage = LeadStage.QUALIFIED if not missing else LeadStage.ENGAGED
        await self.session.flush()
        text = (
            " ".join(schema.question_templates[key] for key in missing[:2])
            if missing
            else ("Requirements collected. The team will confirm the exact price shortly.")
        )
        return state, text
