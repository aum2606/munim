"""MunimBench runner: `make eval`.

    python -m benchmark.run                       # CI mode: oracle "model", fake embedder
    EVAL_USE_REAL_LLM=1 python -m benchmark.run --llm real --embedder local --name mymodel

Needs DATABASE_URL (a migrated Postgres). Creates two benchmark tenants and never touches others.
"""

import argparse
import asyncio
import dataclasses
import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.agents.guardrails import extract_amounts
from app.core.config import Settings, get_settings
from app.core.context import TenantContext
from app.db.models import Channel, ConversationMode, Direction, SenderType
from app.db.session import SessionMaker, make_engine, make_sessionmaker
from app.jobs.handlers import build_handlers
from app.llm.base import LLMClient
from app.llm.embedder import Embedder, FakeEmbedder, LocalEmbedder
from app.llm.openai_compat import ChainLLMClient
from app.orchestrator.dispatch import Route, route_for
from app.orchestrator.messages import canned
from app.orchestrator.pipeline import process_message
from app.orchestrator.pipeline_types import Deps
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.auth import AuthRepository
from app.repositories.chat import ChatRepository
from app.repositories.documents import DocumentRepository
from benchmark.oracle import OracleLLM
from benchmark.schema import BenchItem, load_items
from seeds.data import BUSINESSES
from seeds.load import load_business

REPORTS = Path(__file__).parent / "reports"
_VERTICAL = {"printing": "printing", "photography": "photographer"}


@dataclass
class Outcome:
    item: BenchItem
    reply: str
    intent_ok: bool
    handoff_ok: bool
    grounded_ok: bool | None  # None: not a knowledge question
    retrieval_ok: bool | None  # None: nothing specific was expected to be found
    price_ok: bool | None  # None: no price expected and none shown
    hallucinated: list[int]  # amounts in the reply that were not allowed


async def prepare(
    sessionmaker: SessionMaker, settings: Settings, embedder: Embedder, llm: LLMClient
) -> dict[str, TenantContext]:
    """Create (or reuse) one benchmark tenant per vertical and make sure it is searchable."""
    contexts: dict[str, TenantContext] = {}
    handlers = build_handlers(embedder, settings, llm)
    for vertical, key in _VERTICAL.items():
        business = dataclasses.replace(BUSINESSES[key], owner_email=f"bench-{key}@example.com")
        ctx = await load_business(sessionmaker, business, "bench-" + os.urandom(6).hex(), settings)
        if ctx is None:
            async with sessionmaker() as session:
                owner = await AuthRepository(session).get_user_by_email(business.owner_email)
            assert owner is not None
            ctx = TenantContext(tenant_id=owner.tenant_id, user_id=owner.id)
        await handlers["embed_catalog_items"](sessionmaker, ctx, {})
        async with sessionmaker() as session:
            faqs = await DocumentRepository(session, ctx).browse(faq=True)
        for faq in faqs:
            await handlers["embed_document"](sessionmaker, ctx, {"document_id": str(faq.id)})
        contexts[vertical] = ctx
    return contexts


async def run_item(
    deps: Deps, ctx: TenantContext, item: BenchItem, oracle: OracleLLM | None
) -> Outcome:
    sm = deps.sessionmaker
    async with sm() as session:
        chat = ChatRepository(session, ctx)
        conversation = await chat.start_conversation(Channel.PLAYGROUND, "MunimBench")
        inbound = await chat.add_message(
            conversation, direction=Direction.IN, sender_type=SenderType.CUSTOMER, content=item.text
        )
        await session.commit()
        conversation_id, inbound_id = conversation.id, inbound.id
    if oracle is not None:
        oracle.item = item
    await process_message(deps, ctx, {"conversation_id": str(conversation_id)})

    async with sm() as session:
        chat = ChatRepository(session, ctx)
        messages = await chat.messages(conversation_id)
        conversation = await chat.get_conversation(conversation_id)
        runs = await AgentRunRepository(session, ctx).for_message(inbound_id)
    reply = next(m for m in reversed(messages) if m.direction == Direction.OUT)
    assert conversation is not None

    amounts = extract_amounts(reply.content)
    allowed = set(item.expect.price_paise)
    hallucinated = [a for a in amounts if a not in allowed]
    pricing = item.intent.value == "pricing" and item.expect.grounded
    price_ok = (
        None
        if not (allowed or amounts)
        else (not hallucinated and (not pricing or allowed <= set(amounts)))
    )

    knowledge_run = next((r for r in runs if r.agent == "knowledge"), None)
    retrieval_ok = None
    if item.expect.skus or item.expect.faq:
        shown = knowledge_run.input if knowledge_run else {}
        skus = {i["sku"] for i in shown.get("items", [])}
        titles = {c["title"] for c in shown.get("chunks", [])}
        retrieval_ok = set(item.expect.skus) <= skus and (
            item.expect.faq is None or item.expect.faq in titles
        )

    goes_to_knowledge = (
        route_for_gold(item, deps.settings.router_confidence_threshold) == Route.KNOWLEDGE
    )
    grounded_ok = None
    if goes_to_knowledge:
        answered = reply.content != canned("confirm", item.language)
        grounded_ok = answered == item.expect.grounded

    return Outcome(
        item=item,
        reply=reply.content,
        intent_ok=reply.intent == item.intent.value,
        handoff_ok=(conversation.mode == ConversationMode.HUMAN) == item.handoff,
        grounded_ok=grounded_ok,
        retrieval_ok=retrieval_ok,
        price_ok=price_ok,
        hallucinated=hallucinated,
    )


def route_for_gold(item: BenchItem, threshold: float) -> Route:
    from app.agents.models import RouterOutput

    return route_for(RouterOutput(intent=item.intent, confidence=1.0), threshold)


def pct(values: list[bool]) -> float | None:
    return round(100 * sum(values) / len(values), 1) if values else None


def summarize(outcomes: list[Outcome], *, oracle: bool) -> dict[str, object]:
    def rate(attr: str) -> float | None:
        return pct([v for o in outcomes if (v := getattr(o, attr)) is not None])

    return {
        "items": len(outcomes),
        "intent_accuracy": None if oracle else rate("intent_ok"),  # an oracle proves nothing here
        "handoff_accuracy": rate("handoff_ok"),
        "groundedness": rate("grounded_ok"),
        "retrieval_hit_rate": rate("retrieval_ok"),
        "price_accuracy": rate("price_ok"),
        "hallucinated_amounts": sum(len(o.hallucinated) for o in outcomes),
    }


def render_markdown(name: str, summary: dict[str, object], outcomes: list[Outcome]) -> str:
    lines = [f"# MunimBench: {name}", "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {'n/a' if v is None else v} |" for k, v in summary.items()]
    failed = [
        o for o in outcomes if False in (o.handoff_ok, o.grounded_ok, o.retrieval_ok, o.price_ok)
    ]
    if failed:
        lines += ["", "## Failures", ""]
        lines += [f"- `{o.item.id}` ({o.item.language}): {o.item.text}" for o in failed]
    return "\n".join(lines) + "\n"


async def evaluate(
    sessionmaker: SessionMaker,
    settings: Settings,
    embedder: Embedder,
    llm: LLMClient,
    items: list[BenchItem],
    *,
    include_semantic: bool,
) -> list[Outcome]:
    contexts = await prepare(sessionmaker, settings, embedder, llm)
    oracle = llm if isinstance(llm, OracleLLM) else None
    deps = Deps(llm, embedder, settings, sessionmaker)
    return [
        await run_item(deps, contexts[item.vertical], item, oracle)
        for item in items
        if include_semantic or not item.semantic
    ]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run MunimBench")
    parser.add_argument("--llm", choices=["fake", "real"], default="fake")
    parser.add_argument("--embedder", choices=["fake", "local"], default="fake")
    parser.add_argument("--name", default=None, help="report name (defaults to the llm mode)")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS, help="where to write reports")
    args = parser.parse_args()
    if args.llm == "real" and os.environ.get("EVAL_USE_REAL_LLM") != "1":
        raise SystemExit("Refusing to call a real model: set EVAL_USE_REAL_LLM=1 to allow it.")

    settings = get_settings()
    engine = make_engine(settings.database_url)
    embedder: Embedder = (
        LocalEmbedder(settings.embedding_model, settings.embedding_cache_dir)
        if args.embedder == "local"
        else FakeEmbedder()
    )
    http = httpx.AsyncClient()
    llm: LLMClient = (
        ChainLLMClient.from_settings(settings, http) if args.llm == "real" else OracleLLM()
    )
    try:
        outcomes = await evaluate(
            make_sessionmaker(engine),
            settings,
            embedder,
            llm,
            load_items(),
            include_semantic=args.embedder == "local",
        )
    finally:
        await http.aclose()
        await engine.dispose()

    name = args.name or args.llm
    summary = summarize(outcomes, oracle=args.llm == "fake")
    reports = args.reports_dir
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "summary": summary,
                "outcomes": [
                    {
                        "id": o.item.id,
                        "reply": o.reply,
                        "hallucinated": o.hallucinated,
                        "handoff_ok": o.handoff_ok,
                        "grounded_ok": o.grounded_ok,
                        "retrieval_ok": o.retrieval_ok,
                        "price_ok": o.price_ok,
                        "intent_ok": o.intent_ok,
                    }
                    for o in outcomes
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    markdown = render_markdown(name, summary, outcomes)
    (reports / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    if summary["hallucinated_amounts"] or summary["price_accuracy"] not in (None, 100.0):
        raise SystemExit(1)  # a wrong price is always a failed run


if __name__ == "__main__":
    asyncio.run(main())
