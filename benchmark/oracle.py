"""A stand-in "model" that answers from each benchmark item's gold labels.

It lets CI check everything around the model (retrieval, price rendering, guardrails, dispatch)
without calling a real LLM. It says nothing about model quality: that needs `--llm real`.
"""

import json
import re

from app.llm.base import ChatMessage, LLMClient, LLMResult, Slot
from benchmark.schema import BenchItem

_ITEM_LINE = re.compile(r"^id=([0-9a-f-]{36}) \| (.+?) \(sku (\S+)\)", re.MULTILINE)
_CHUNK = re.compile(r"^id=([0-9a-f-]{36}) \| ([^\n]+)\n(.*?)(?:\n\n|\Z)", re.MULTILINE | re.DOTALL)


class OracleLLM(LLMClient):
    def __init__(self) -> None:
        self.item: BenchItem | None = None

    async def complete(
        self, slot: Slot, messages: list[ChatMessage], *, json_mode: bool = False
    ) -> LLMResult:
        item = self.item
        if item is None:
            raise RuntimeError("OracleLLM needs a benchmark item")
        system, user = messages[1].content, messages[2].content
        if "You classify the latest customer message" in system:
            reply = {
                "intent": item.intent.value,
                "language": item.language,
                "script": item.script,
                "mentioned_catalog_terms": item.terms,
                "confidence": 0.95,
            }
        elif "answer the customer's question using ONLY the evidence" in system:
            reply = self._knowledge(item, user)
        elif "You write the reply to a customer" in system:
            reply = {"reply": self._responder(user)}
        else:
            raise RuntimeError("OracleLLM does not know this prompt")
        return LLMResult(json.dumps(reply), "oracle", "oracle-1")

    @staticmethod
    def _knowledge(item: BenchItem, user: str) -> dict[str, object]:
        gap = {"grounded": False, "answer_points": [], "gap_question": item.text}
        if not item.expect.grounded:
            return gap
        sku_ids = {sku: (i, name) for i, name, sku in _ITEM_LINE.findall(user)}
        items = [sku_ids[s] for s in item.expect.skus if s in sku_ids]
        chunks = [
            (cid, content)
            for cid, title, content in _CHUNK.findall(user.split("<knowledge>")[-1])
            if item.expect.faq and title.strip() == item.expect.faq
        ]
        retrieved = (not item.expect.skus or len(items) == len(item.expect.skus)) and (
            not item.expect.faq or chunks
        )
        if not retrieved:  # retrieval missed what a correct answer needs: the model cannot cite it
            return gap
        points = [f"{name} is available." for _, name in items]
        points += [c.split("\nA: ", 1)[-1].strip() for _, c in chunks]
        return {
            "grounded": True,
            "answer_points": points,
            "cited_item_ids": [i for i, _ in items],
            "price_item_ids": [i for i, _ in items] if item.expect.price_paise else [],
            "cited_chunk_ids": [c for c, _ in chunks],
        }

    @staticmethod
    def _responder(user: str) -> str:
        points_block, _, lines_block = user.partition("Price lines (copy exactly):")
        bullets = [
            line[2:].strip()
            for block in (points_block.split("Answer points:")[-1], lines_block)
            for line in block.splitlines()
            if line.startswith("- ")
        ]
        return "\n".join(bullets)
