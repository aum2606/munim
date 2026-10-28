import asyncio
from pathlib import Path

import pytest

from app.agents.evaluation import CaseResult, load_cases, main, run_cases, summarize, write_report
from app.core.config import Settings
from app.llm import FakeLLM
from app.llm.offline import agent_response
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.evaluation import EvaluationRepository

CASES = load_cases(Path(__file__).with_name("pilot_contracts.yaml"))


async def test_five_vertical_report_meets_contract_targets(sessions):
    async with sessions() as session:
        ctx, facts = await EvaluationRepository(session).create_workspace()
    llm = FakeLLM(DatabaseRunRecorder(sessions), {}, fallback=agent_response)
    report = await run_cases(llm, ctx, CASES, facts)
    await asyncio.to_thread(write_report, report, Path(Settings().eval_report_path))
    assert report.mode == "fake" and report.passed, report.model_dump_json(indent=2)
    assert {case.vertical for case in report.cases} == {
        "printing",
        "photography",
        "interior",
        "repair",
        "electronics",
    }
    assert report.metrics["price_accuracy"].percent == "100.00"
    assert len(llm.calls) > len(CASES)


def test_report_does_not_hide_missing_samples_or_failures():
    assert not summarize([], "fake").passed
    report = summarize(
        [
            CaseResult(
                id="failure",
                vertical="printing",
                checks={"price_accuracy": False},
                latency_ms=0,
                error="GuardrailViolation",
            )
        ],
        "fake",
    )
    assert not report.passed
    assert report.metrics["price_accuracy"].percent == "0.00"
    assert report.metrics["groundedness"].percent is None


async def test_real_evaluation_requires_explicit_dedicated_database(monkeypatch):
    monkeypatch.setenv("EVAL_USE_REAL_LLM", "1")
    monkeypatch.setenv("EVAL_DATABASE_URL", "")
    with pytest.raises(SystemExit, match="dedicated EVAL_DATABASE_URL"):
        await main()
