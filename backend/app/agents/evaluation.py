"""Agent contract metrics; real-model evaluation is a separate explicitly gated CLI."""

import asyncio
import json
import statistics
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.agents.guardrails import GuardrailViolation, check_reply
from app.agents.knowledge import KnowledgeAgent
from app.agents.requirements import RequirementsAgent
from app.agents.responder import ResponderAgent
from app.agents.router import RouterAgent
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.llm import FakeLLM, LLMClient
from app.orchestrator.localized import fallback, grounded_message
from app.schemas.agents import AgentMessage, Intent, KnowledgeInput, ResponderInput, RouterInput
from app.schemas.knowledge import Fact, StrictModel
from app.schemas.requirements import Category, RequirementsInput


class GoldenCase(StrictModel):
    id: str
    vertical: Category
    question: str
    intent: Intent
    kind: Literal["knowledge", "refusal", "handoff", "slots"] = "knowledge"
    slots: dict[str, str] = Field(default_factory=dict)


class CaseResult(BaseModel):
    id: str
    vertical: str
    checks: dict[str, bool]
    latency_ms: int
    error: str | None = None


class EvalMetric(BaseModel):
    passed: int
    total: int
    percent: str | None
    threshold: str
    meets_target: bool


class EvalReport(BaseModel):
    version: int = 1
    mode: Literal["fake", "real"]
    generated_at: datetime
    passed: bool
    metrics: dict[str, EvalMetric]
    median_case_latency_ms: int
    cases: list[CaseResult]
    limitation: str


TARGETS = {
    "intent_accuracy": "95",
    "groundedness": "95",
    "price_accuracy": "100",
    "refusal_correctness": "100",
    "slot_filling": "95",
    "handoff_correctness": "100",
}


def summarize(results: list[CaseResult], mode: Literal["fake", "real"]) -> EvalReport:
    metrics = {}
    for name, threshold in TARGETS.items():
        checks = [result.checks[name] for result in results if name in result.checks]
        percent = Decimal(sum(checks)) * 100 / Decimal(len(checks)) if checks else None
        metrics[name] = EvalMetric(
            passed=sum(checks),
            total=len(checks),
            percent=str(percent.quantize(Decimal("0.01"))) if percent is not None else None,
            threshold=threshold,
            meets_target=percent is not None and percent >= Decimal(threshold),
        )
    return EvalReport(
        mode=mode,
        generated_at=datetime.now(UTC),
        passed=bool(results)
        and all(metric.meets_target for metric in metrics.values())
        and all(result.error is None for result in results),
        metrics=metrics,
        median_case_latency_ms=int(statistics.median([result.latency_ms for result in results]))
        if results
        else 0,
        cases=results,
        limitation=(
            "Scripted contract checks; not evidence of production model quality or pilot outcomes."
            if mode == "fake"
            else "Synthetic agent contracts; not a live-business pilot or retrieval benchmark."
        ),
    )


async def run_cases(
    llm: LLMClient, ctx: TenantContext, cases: list[GoldenCase], facts: dict[Category, Fact]
) -> EvalReport:
    results = []
    for case in cases:
        fact = facts[case.vertical]
        started = time.perf_counter_ns()
        checks: dict[str, bool] = {"intent_accuracy": False}
        error_name = None
        if case.kind == "knowledge":
            checks.update(groundedness=False, price_accuracy=False)
        elif case.kind == "slots":
            checks["slot_filling"] = False
        elif case.kind == "handoff":
            checks["handoff_correctness"] = False
        else:
            checks["refusal_correctness"] = False
        try:
            route = await RouterAgent(llm).run(
                ctx,
                RouterInput(
                    messages=[AgentMessage(direction="in", content=case.question)],
                    business_type=case.vertical,
                ),
            )
            checks["intent_accuracy"] = route.intent == case.intent
            if case.kind == "slots":
                extraction = await RequirementsAgent(llm).run(
                    ctx,
                    RequirementsInput(
                        question=case.question,
                        category=case.vertical,
                        slots=list(case.slots),
                        awaiting=[],
                        filled=[],
                    ),
                )
                extracted = {entry.key: entry.value for entry in extraction.updates}
                checks["slot_filling"] = extracted == case.slots
            elif case.kind == "handoff":
                # This is the orchestrator's deterministic handoff predicate, not a model's action.
                checks["handoff_correctness"] = route.intent in {
                    Intent.COMPLAINT,
                    Intent.HUMAN_REQUEST,
                    Intent.NEGOTIATION,
                }
            elif case.kind == "refusal":
                trusted = fallback(route.language)
                output = await ResponderAgent(llm).run(
                    ctx,
                    ResponderInput(
                        question=case.question,
                        language=route.language,
                        tone="friendly",
                        trusted_messages=[trusted],
                        violation=None,
                    ),
                )
                check_reply(output.text, set(), [trusted])
                checks["refusal_correctness"] = output.text == trusted
            else:
                agent = KnowledgeAgent(llm)
                answer = await agent.run(ctx, KnowledgeInput(question=case.question, facts=[fact]))
                selected = agent.grounded_facts(answer, [fact])
                trusted = grounded_message(route.language, [entry.text for entry in selected])
                output = await ResponderAgent(llm).run(
                    ctx,
                    ResponderInput(
                        question=case.question,
                        language=route.language,
                        tone="friendly",
                        trusted_messages=[trusted],
                        violation=None,
                    ),
                )
                allowed = {fact.price.paise} if fact.price else set()
                check_reply(output.text, allowed, [trusted])
                checks["groundedness"] = bool(selected)
                checks["price_accuracy"] = (
                    fact.price is not None and fact.price.formatted in output.text
                )
        except (
            DomainError,
            ValidationError,
            ValueError,
            httpx.HTTPError,
            PermissionError,
        ) as error:
            error_name = type(error).__name__
            if isinstance(error, GuardrailViolation) and case.kind == "knowledge":
                checks["groundedness"] = False
                checks["price_accuracy"] = False
        results.append(
            CaseResult(
                id=case.id,
                vertical=case.vertical,
                checks=checks,
                latency_ms=(time.perf_counter_ns() - started) // 1_000_000,
                error=error_name,
            )
        )
    return summarize(results, "fake" if isinstance(llm, FakeLLM) else "real")


def load_cases(path: Path) -> list[GoldenCase]:
    # JSON is valid YAML; the checked-in suite uses this subset to keep runtime dependencies small.
    return [
        GoldenCase.model_validate(case) for case in json.loads(path.read_text(encoding="utf-8"))
    ]


def write_report(report: EvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


async def main() -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import Settings
    from app.llm import OpenAICompatibleLLM
    from app.repositories.agent_runs import DatabaseRunRecorder
    from app.repositories.evaluation import EvaluationRepository

    settings = Settings()
    if not settings.eval_use_real_llm:
        raise SystemExit(
            "Real evaluation requires EVAL_USE_REAL_LLM=1; use make eval for offline checks"
        )
    if settings.app_env == "prod" or not settings.eval_database_url:
        raise SystemExit("Use a dedicated EVAL_DATABASE_URL in a non-production environment")
    if not settings.llm_api_key.get_secret_value() or not all(
        (settings.llm_model_router, settings.llm_model_reasoning, settings.llm_model_cheap)
    ):
        raise SystemExit(
            "Configure all LLM models and the provider credential before real evaluation"
        )
    engine = create_async_engine(settings.eval_database_url, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            ctx, facts = await EvaluationRepository(session).create_workspace()
        llm = OpenAICompatibleLLM(DatabaseRunRecorder(sessions), settings)
        root = Path(__file__).parents[2]
        cases = await asyncio.to_thread(load_cases, root / "tests/evals/pilot_contracts.yaml")
        report = await run_cases(llm, ctx, cases, facts)
        await asyncio.to_thread(write_report, report, Path(settings.eval_report_path))
        print(f"Real evaluation passed={report.passed}; report: {settings.eval_report_path}")
        return 0 if report.passed else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
