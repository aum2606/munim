import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.agents.base import BaseAgent, ToolBox
from app.agents.guardrails import extract_amounts
from app.agents.models import (
    ChunkEvidence,
    ItemEvidence,
    KnowledgeAnswer,
    KnowledgeInput,
    RouterOutput,
    Turn,
)
from app.core.context import TenantContext
from app.llm.prompting import sanitize_customer_text
from app.pricing.inr import format_inr
from app.repositories.documents import ChunkHit
from app.tools.business_info import BusinessInfo
from app.tools.catalog_lookup import CatalogHit

_MAX_CHUNK_CHARS = 1200


@dataclass(frozen=True)
class KnowledgeResult:
    answer: KnowledgeAnswer
    price_lines: list[str]  # built here from catalogue paise, never by the model
    allowed_paise: frozenset[int]  # every price a tool returned this turn


def price_line(hit: CatalogHit) -> str:
    return f"{hit.name}: {format_inr(hit.base_price_paise)} {hit.unit} + {hit.gst_rate}% GST"


class KnowledgeAgent(BaseAgent):
    name = "knowledge"
    template = "knowledge"
    slot = "large"
    # Read-only: it can look things up but cannot create quotes, change prices or message anyone.
    tools = frozenset({"search_knowledge", "lookup_catalog", "get_business_info"})

    def toolbox(self, available: dict[str, Callable[..., Awaitable[Any]]]) -> ToolBox:
        return ToolBox(self.tools, available)

    async def run(
        self,
        ctx: TenantContext,
        *,
        question: str,
        turns: list[Turn],
        router: RouterOutput,
        toolbox: ToolBox,
        message_id: uuid.UUID | None = None,
    ) -> KnowledgeResult:
        items: list[CatalogHit] = await toolbox.call(
            "lookup_catalog", terms=router.mentioned_catalog_terms or [question]
        )
        chunks: list[ChunkHit] = await toolbox.call("search_knowledge", query=question)
        business: BusinessInfo = await toolbox.call("get_business_info")
        # Prices of products come from the catalogue. Amounts the owner wrote in their own
        # policies (a delivery threshold, an advance) may be repeated exactly as written.
        policy_amounts = {a for c in chunks for a in extract_amounts(c.content) if a >= 0}
        allowed = frozenset({i.base_price_paise for i in items} | policy_amounts)

        if not items and not chunks:  # nothing retrieved: do not even ask the model
            return KnowledgeResult(
                KnowledgeAnswer(grounded=False, gap_question=question), [], allowed
            )

        data = KnowledgeInput(
            question=question,
            turns=turns,
            router=router,
            business=business,
            chunks=[
                ChunkEvidence(
                    chunk_id=c.chunk_id, title=c.title, content=c.content[:_MAX_CHUNK_CHARS]
                )
                for c in chunks
            ],
            items=[
                ItemEvidence(
                    item_id=i.item_id,
                    sku=i.sku,
                    name=i.name,
                    unit=i.unit,
                    price=format_inr(i.base_price_paise),
                    gst_rate=i.gst_rate,
                    stock_status=i.stock_status,
                    description=i.description,
                )
                for i in items
            ],
        )
        answer = await self.invoke(
            ctx,
            KnowledgeAnswer,
            data,
            message_id=message_id,
            toolbox=toolbox,
            question=sanitize_customer_text(question),
            business=business,
            chunks=data.chunks,
            items=data.items,
        )
        return self._verified(answer, items, chunks, allowed, question)

    @staticmethod
    def _verified(
        answer: KnowledgeAnswer,
        items: list[CatalogHit],
        chunks: list[ChunkHit],
        allowed: frozenset[int],
        question: str,
    ) -> KnowledgeResult:
        """Do not trust the model's own claims: keep only ids we really retrieved, and treat an
        answer that cites nothing real as ungrounded."""
        by_item = {i.item_id: i for i in items}
        real_chunks = {c.chunk_id for c in chunks}
        answer.cited_chunk_ids = [c for c in answer.cited_chunk_ids if c in real_chunks]
        answer.cited_item_ids = [i for i in answer.cited_item_ids if i in by_item]
        answer.price_item_ids = [i for i in answer.price_item_ids if i in by_item]
        if answer.grounded and not (answer.cited_chunk_ids or answer.cited_item_ids):
            answer.grounded = False
        if not answer.grounded or not answer.answer_points:
            return KnowledgeResult(
                KnowledgeAnswer(grounded=False, gap_question=answer.gap_question or question),
                [],
                allowed,
            )
        lines = [price_line(by_item[i]) for i in dict.fromkeys(answer.price_item_ids)]
        return KnowledgeResult(answer, lines, allowed)
