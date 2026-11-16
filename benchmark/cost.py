"""Cost and latency report from `agent_runs`: `make cost`.

    python -m benchmark.cost            # the two benchmark tenants, written to reports/cost.md

Run it after `make eval` (a real model gives real numbers; the oracle model costs nothing).
Costs are at list price even on a free tier (app/llm/costs.py), in US dollars.
"""

import asyncio

from app.core.config import get_settings
from app.core.context import TenantContext
from app.db.session import make_engine, make_sessionmaker
from app.repositories.auth import AuthRepository
from app.tools.metrics import UsageReport, usage_report
from benchmark.run import REPORTS

VERTICALS = {
    "printing": "bench-printing@example.com",
    "photography": "bench-photographer@example.com",
}


def usd(micros: int) -> str:
    return f"${micros / 1_000_000:.4f}"


def render(name: str, report: UsageReport) -> str:
    lines = [
        f"## {name}",
        "",
        f"- customer turns with a model call: {report.turns}",
        f"- cost per turn at list price: {usd(report.cost_per_turn_micros)} "
        f"(total {usd(report.cost_micros)})",
    ]
    if report.first_response_p50_ms is not None:
        lines.append(
            f"- first response (customer message to AI reply, includes the debounce wait): "
            f"p50 {report.first_response_p50_ms} ms, p95 {report.first_response_p95_ms} ms"
        )
    if report.unpriced_calls:
        lines.append(
            f"- {report.unpriced_calls} calls used a model with no listed price: understated"
        )
    lines += [
        "",
        "| agent | model | calls | errors | tokens in | tokens out | cost | p50 ms | p95 ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.agent} | {r.model or '-'} | {r.calls} | {r.errors} | {r.prompt_tokens} | "
        f"{r.completion_tokens} | {usd(r.cost_micros)} | {r.p50_ms} | {r.p95_ms} |"
        for r in report.rows
    ]
    return "\n".join(lines) + "\n"


async def main() -> None:
    engine = make_engine(get_settings().database_url)
    sessionmaker = make_sessionmaker(engine)
    sections = ["# Cost and latency", ""]
    async with sessionmaker() as session:
        for name, email in VERTICALS.items():
            owner = await AuthRepository(session).get_user_by_email(email)
            if owner is None:
                continue
            ctx = TenantContext(tenant_id=owner.tenant_id, user_id=owner.id)
            sections.append(render(name, await usage_report(session, ctx)))
    await engine.dispose()
    out = "\n".join(sections)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "cost.md").write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    asyncio.run(main())
