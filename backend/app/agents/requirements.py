from app.agents.base import BaseAgent
from app.llm import LLMClient
from app.schemas.requirements import RequirementsInput, RequirementsOutput


class RequirementsAgent(BaseAgent[RequirementsInput, RequirementsOutput]):
    name = "requirements"
    model_slot = "reasoning"
    allowed_tools = ()

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, RequirementsOutput)
