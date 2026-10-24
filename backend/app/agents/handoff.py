from app.agents.base import BaseAgent
from app.llm import LLMClient
from app.schemas.leads import HandoffInput, HandoffOutput


class HandoffAgent(BaseAgent[HandoffInput, HandoffOutput]):
    name = "handoff"
    model_slot = "cheap"
    allowed_tools = ()

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, HandoffOutput)
