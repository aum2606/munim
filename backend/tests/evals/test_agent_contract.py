from pathlib import Path
from uuid import uuid4

import yaml

from app.agents.router import RouterAgent
from app.core.tenant import TenantContext
from app.llm import FakeLLM
from app.llm.fake import input_hash
from app.llm.offline import agent_response
from app.llm.types import LLMRequest
from app.schemas.agents import AgentMessage, RouterInput


class Recorder:
    async def record(self, ctx, **run):
        pass


async def test_golden_router_contracts():
    for case in yaml.safe_load(
        (Path(__file__).parent / "knowledge_contract.yaml").read_text(encoding="utf-8")
    ):
        body = RouterInput(
            messages=[AgentMessage(direction="in", content=case["message"])],
            business_type="electronics",
        )
        request = LLMRequest(agent="router", system="", content=body, output_schema={})
        fake = FakeLLM(Recorder(), {("router", input_hash(request)): [agent_response(request)]})
        result = await RouterAgent(fake).run(TenantContext(uuid4()), body)
        assert result.intent == case["intent"] and result.language == case["language"]
