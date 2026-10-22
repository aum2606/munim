from app.agents.base import BaseAgent
from app.llm import LLMClient
from app.schemas.agents import RouterInput, RouterOutput


class RouterAgent(BaseAgent[RouterInput, RouterOutput]):
    name = "router"
    model_slot = "router"
    allowed_tools = ()

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, RouterOutput)
