from pathlib import Path
from uuid import uuid4

import yaml

from app.agents.requirements import RequirementsAgent
from app.core.tenant import TenantContext
from app.llm import FakeLLM
from app.llm.offline import agent_response
from app.schemas.requirements import RequirementsInput
from tests.unit.test_agents import MemoryRecorder


async def test_requirement_extraction_golden_contract():
    cases = yaml.safe_load(
        (Path(__file__).parent / "requirements_conversations.yaml").read_text(encoding="utf-8")
    )
    fake = FakeLLM(MemoryRecorder(), {}, fallback=agent_response)
    for case in cases:
        result = await RequirementsAgent(fake).run(
            TenantContext(uuid4()),
            RequirementsInput(
                question=case["question"],
                category="printing",
                slots=["quantity", "sides", "size", "material", "deadline"],
                awaiting=case["awaiting"],
                filled=[],
            ),
        )
        assert {update.key: update.value for update in result.updates} == case["expected"]
