from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tenant import TenantContext
from app.llm import FakeLLM
from app.llm.fake import input_hash
from app.llm.types import LLMRequest, LLMResponse
from app.repositories.agent_runs import AgentRunRepository, DatabaseRunRecorder
from app.repositories.identity import IdentityRepository


class Payload(BaseModel):
    text: str


async def test_persisted_success_failure_and_tenant_isolation(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        identity = IdentityRepository(session)
        a = await identity.register("A", "printing", f"{uuid4()}@example.com", "A", "not-used")
        b = await identity.register("B", "printing", f"{uuid4()}@example.com", "B", "not-used")
        await session.commit()
    ctx_a, ctx_b = TenantContext(a.tenant_id), TenantContext(b.tenant_id)
    req = LLMRequest(
        agent="test",
        system="Grounded only",
        content=Payload(text="demo@example.com +91 98765 43210"),
        output_schema=Payload.model_json_schema(),
    )
    fake = FakeLLM(
        DatabaseRunRecorder(sessions),
        {
            (req.agent, input_hash(req)): [
                LLMResponse(output={"text": "demo@example.com"}),
                RuntimeError("PII should not be stored"),
            ]
        },
    )
    await fake.structured(ctx_a, req, Payload)
    with pytest.raises(RuntimeError):
        await fake.structured(ctx_a, req, Payload)
    async with sessions() as session:
        runs = await AgentRunRepository(session, ctx_a).list()
        assert len(runs) == 2
        assert {run.status for run in runs} == {"success", "error"}
        assert "demo@example.com" not in str([run.input for run in runs])
        assert "demo@example.com" not in str([run.output for run in runs])
        assert "98765" not in str([run.input for run in runs])
        assert await AgentRunRepository(session, ctx_b).list() == []
