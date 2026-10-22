from app.agents.base import BaseAgent
from app.llm import LLMClient
from app.schemas.agents import ResponderInput, ResponderOutput


class ResponderAgent(BaseAgent[ResponderInput, ResponderOutput]):
    name = "responder"
    model_slot = "cheap"
    allowed_tools = ()

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, ResponderOutput)
