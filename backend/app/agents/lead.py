from app.agents.base import BaseAgent
from app.llm import LLMClient
from app.schemas.leads import LeadInput, LeadOutput


class LeadAgent(BaseAgent[LeadInput, LeadOutput]):
    name = "lead"
    model_slot = "cheap"
    allowed_tools = ()

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, LeadOutput)
