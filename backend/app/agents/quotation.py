from app.agents.base import BaseAgent
from app.llm import LLMClient
from app.schemas.quotes import QuotationInput, QuotationOutput


class QuotationAgent(BaseAgent[QuotationInput, QuotationOutput]):
    name = "quotation"
    model_slot = "reasoning"
    allowed_tools = ("lookup_catalog", "price_quote", "render_quote_pdf")

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, QuotationOutput)
