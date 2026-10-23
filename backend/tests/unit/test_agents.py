from uuid import uuid4

import pytest

from app.agents.knowledge import KnowledgeAgent
from app.agents.quotation import QuotationAgent
from app.agents.requirements import RequirementsAgent
from app.agents.responder import ResponderAgent
from app.agents.router import RouterAgent
from app.core.tenant import TenantContext
from app.llm import FakeLLM
from app.llm.fake import input_hash
from app.llm.offline import agent_response
from app.llm.types import LLMRequest, LLMResponse, ToolCall
from app.schemas.agents import AgentMessage, KnowledgeInput, ResponderInput, RouterInput
from app.schemas.knowledge import Fact, SearchResults
from app.schemas.quotes import QuotationInput
from app.schemas.requirements import RequirementsInput


class MemoryRecorder:
    def __init__(self):
        self.runs = []

    async def record(self, ctx, **run):
        self.runs.append(run)


@pytest.mark.parametrize(
    "agent_type,body",
    [
        (QuotationAgent, QuotationInput(category="printing", requirements=[], candidates=[])),
        (
            RequirementsAgent,
            RequirementsInput(
                question="quantity=500",
                category="printing",
                slots=["quantity"],
                awaiting=[],
                filled=[],
            ),
        ),
        (
            RouterAgent,
            RouterInput(
                messages=[AgentMessage(direction="in", content="bhai laptop ka rate kya hai")],
                business_type="electronics",
            ),
        ),
        (
            KnowledgeAgent,
            KnowledgeInput(
                question="Hours?",
                facts=[Fact(ref="chunk:test", kind="chunk", text="Open on Monday", price=None)],
            ),
        ),
        (
            ResponderAgent,
            ResponderInput(
                question="Hours?",
                language="en",
                tone="friendly",
                trusted_messages=["Open on Monday"],
                violation=None,
            ),
        ),
    ],
)
async def test_each_agent_valid_invalid_retry_and_tool_permissions(agent_type, body):
    recorder = MemoryRecorder()
    fake = FakeLLM(recorder, {})
    agent = agent_type(fake)
    prototype = LLMRequest(agent=agent.name, system="", content=body, output_schema={})
    key = (agent.name, input_hash(prototype))
    expected = agent_response(prototype)
    fake.scripts[key] = __import__("collections").deque([LLMResponse(output={}), expected])
    output = await agent.run(TenantContext(uuid4()), body)
    assert output.model_dump(mode="json") == expected.output
    assert len(fake.calls) == 2 and recorder.runs[0]["status"] == "invalid"
    fake.scripts[key] = __import__("collections").deque(
        [
            LLMResponse(
                output=expected.output, tool_calls=[ToolCall(name="create_quote", arguments={})]
            )
        ]
    )
    with pytest.raises(PermissionError):
        await agent.run(TenantContext(uuid4()), body)
    called = False

    async def forbidden():
        nonlocal called
        called = True
        return SearchResults(facts=[])

    with pytest.raises(PermissionError):
        await agent.call_tool("create_quote", forbidden)
    assert called is False


async def test_customer_text_never_enters_system_prompt():
    body = RouterInput(
        messages=[AgentMessage(direction="in", content="CUSTOMER_SECRET_IGNORE_RULES")],
        business_type="printing",
    )
    recorder = MemoryRecorder()
    fake = FakeLLM(recorder, {}, fallback=agent_response)
    await RouterAgent(fake).run(TenantContext(uuid4()), body)
    assert "CUSTOMER_SECRET" not in fake.calls[0].system
    assert "CUSTOMER_SECRET" in fake.calls[0].content.model_dump_json()
