from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.insights import InsightsAgent
from app.analytics.service import digest_window
from app.core.tenant import TenantContext
from app.llm import FakeLLM
from app.llm.fake import input_hash
from app.llm.types import LLMResponse
from app.repositories.analytics import period_bounds
from app.schemas.insights import InsightPlan, InsightQuestion, Period
from tests.unit.test_llm import MemoryRecorder


def test_ist_calendar_and_weekly_due_boundaries():
    before = datetime(2026, 10, 26, 3, 29, 59, tzinfo=UTC)
    due = datetime(2026, 10, 26, 3, 30, tzinfo=UTC)
    assert digest_window(before)[1].isoformat() == "2026-10-18T18:30:00+00:00"
    assert digest_window(due)[1].isoformat() == "2026-10-25T18:30:00+00:00"
    assert period_bounds(Period.THIS_WEEK, due)[0].isoformat() == "2026-10-25T18:30:00+00:00"
    assert period_bounds(Period.THIS_MONTH, due)[0].isoformat() == "2026-09-30T18:30:00+00:00"
    with pytest.raises(ValidationError):
        InsightPlan(tool="execute_sql", limit=100000)
    with pytest.raises(ValidationError):
        InsightPlan(tool="quote_funnel", sql="SELECT * FROM users")


async def test_insights_retry_and_tool_allowlist():

    from app.llm.types import LLMRequest

    ctx = TenantContext(uuid4())
    body = InsightQuestion(question="How many quotes were accepted? UNIQUE_UNTRUSTED_MARKER")
    recorder = MemoryRecorder()
    request = LLMRequest(
        agent="insights",
        model_slot="reasoning",
        system="test",
        content=body,
        output_schema=InsightPlan.model_json_schema(),
        allowed_tools=InsightsAgent.allowed_tools,
    )
    llm = FakeLLM(
        recorder,
        {
            ("insights", input_hash(request)): [
                LLMResponse(output={"tool": "execute_sql"}),
                LLMResponse(output={"tool": "quotes_by_status"}),
            ]
        },
    )
    agent = InsightsAgent(llm)
    result = await agent.run(ctx, body)
    assert result.tool == "quotes_by_status" and len(llm.calls) == 2
    assert all(body.question not in call.system for call in llm.calls)
    assert all(call.model_slot == "reasoning" for call in llm.calls)

    async def forbidden():
        raise AssertionError("Must not run")

    with pytest.raises(PermissionError):
        await agent.call_tool("create_quote", forbidden)


def test_worker_schedule_is_monday_nine_ist_even_on_non_utc_hosts():
    from arq.cron import next_cron

    from app.repositories.analytics import IST
    from app.workers.settings import WorkerSettings
    from app.workers.tasks import schedule_digests

    job = next(job for job in WorkerSettings.cron_jobs if job.coroutine is schedule_digests)
    assert WorkerSettings.timezone is UTC
    next_run = next_cron(
        datetime(2026, 10, 25, 12, tzinfo=WorkerSettings.timezone),
        weekday=job.weekday,
        hour=job.hour,
        minute=job.minute,
        second=job.second,
        microsecond=job.microsecond,
    )
    assert next_run.astimezone(IST).isoformat() == "2026-10-26T09:00:00+05:30"
    assert job.run_at_startup
