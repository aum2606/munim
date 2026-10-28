from pathlib import Path

import pytest
import yaml

from app.analytics.service import InsightsService
from app.llm import FakeLLM
from app.llm.offline import agent_response
from app.repositories.agent_runs import DatabaseRunRecorder
from app.schemas.insights import InsightQuestion
from tests.integration.test_analytics import NOW, seed_analytics
from tests.integration.test_workspace import owner

CASES = yaml.safe_load(
    Path(__file__).with_name("phase5_conversations.yaml").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES, ids=[case["tool"] for case in CASES])
async def test_insights_acceptance_against_seeded_facts(client, sessions, case):
    _, ctx, _ = await owner(client)
    async with sessions() as session:
        await seed_analytics(session, ctx)
        llm = FakeLLM(DatabaseRunRecorder(sessions), {}, fallback=agent_response)
        answer = await InsightsService(session, ctx).ask(
            InsightQuestion(question=case["question"]), llm, NOW
        )
        assert answer.tool == case["tool"]
        assert answer.total == case["total"]
        assert case["text_contains"] in answer.text
        if answer.chart_spec:
            assert answer.chart_spec.rows == answer.table
