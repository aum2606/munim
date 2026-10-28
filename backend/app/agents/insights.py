from app.agents.base import BaseAgent
from app.llm import LLMClient
from app.schemas.insights import AnalyticsTool, InsightPlan, InsightQuestion


class InsightsAgent(BaseAgent[InsightQuestion, InsightPlan]):
    name = "insights"
    allowed_tools = tuple(tool.value for tool in AnalyticsTool)

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, InsightPlan)
