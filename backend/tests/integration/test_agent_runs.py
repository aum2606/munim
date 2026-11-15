import pytest
from pydantic import BaseModel

from app.db.models import AgentRunStatus
from app.db.session import SessionMaker
from app.llm.base import ChatMessage
from app.llm.fake import FakeLLM
from app.llm.recording import agent_run
from app.repositories.agent_runs import AgentRunRepository
from tests.conftest import make_tenant


class Out(BaseModel):
    intent: str


async def test_successful_call_is_recorded(sessionmaker: SessionMaker) -> None:
    ctx = await make_tenant(sessionmaker)
    llm = FakeLLM(['{"intent": "greeting"}'])
    async with agent_run(
        sessionmaker, ctx, agent="router", prompt_version="router@abc123", input={"text": "hi"}
    ) as run:
        parsed, run.result = await llm.structured(
            "small", [ChatMessage(role="user", content="hi")], Out
        )
        run.output = parsed.model_dump()

    async with sessionmaker() as session:
        (row,) = await AgentRunRepository(session, ctx).list_recent()
    assert (row.agent, row.status, row.provider, row.model) == (
        "router",
        AgentRunStatus.OK,
        "fake",
        "fake-1",
    )
    assert row.output == {"intent": "greeting"} and row.prompt_tokens == 10
    assert row.prompt_version == "router@abc123"


async def test_failed_call_is_recorded_and_the_error_propagates(sessionmaker: SessionMaker) -> None:
    ctx = await make_tenant(sessionmaker)
    with pytest.raises(RuntimeError):
        async with agent_run(sessionmaker, ctx, agent="knowledge", prompt_version="k@1", input={}):
            raise RuntimeError("boom with customer text 9876543210")

    async with sessionmaker() as session:
        (row,) = await AgentRunRepository(session, ctx).list_recent()
    assert row.status == AgentRunStatus.ERROR
    assert row.error == "RuntimeError"  # class only; the message is never stored


async def test_agent_runs_are_tenant_isolated(sessionmaker: SessionMaker) -> None:
    a, b = await make_tenant(sessionmaker), await make_tenant(sessionmaker)
    async with agent_run(sessionmaker, a, agent="router", prompt_version="r@1", input={}):
        pass
    async with sessionmaker() as session:
        assert len(await AgentRunRepository(session, a).list_recent()) == 1
        assert await AgentRunRepository(session, b).list_recent() == []
