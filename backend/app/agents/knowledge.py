from app.agents.base import BaseAgent
from app.core.errors import DomainError
from app.llm import LLMClient
from app.schemas.agents import KnowledgeAnswer, KnowledgeInput
from app.schemas.knowledge import Fact


class KnowledgeAgent(BaseAgent[KnowledgeInput, KnowledgeAnswer]):
    name = "knowledge"
    allowed_tools = ("search_knowledge", "lookup_catalog", "get_business_info")

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, KnowledgeAnswer)

    def grounded_facts(self, answer: KnowledgeAnswer, facts: list[Fact]) -> list[Fact]:
        by_ref = {fact.ref: fact for fact in facts}
        if (
            not answer.grounded
            or not answer.citations
            or not set(answer.citations).issubset(by_ref)
        ):
            raise DomainError("Answer is not grounded")
        selected = [by_ref[ref] for ref in dict.fromkeys(answer.citations)]
        trusted_prices = [fact.price for fact in selected if fact.price is not None]
        if any(price not in trusted_prices for price in answer.prices):
            raise DomainError("Answer includes an untrusted price")
        # Unverified prose is never promoted to customer-facing evidence.
        return selected
