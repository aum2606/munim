"""The benchmark harness runs in CI with the oracle model and fake embedder. This proves the
plumbing (retrieval, price rendering, guardrails, dispatch) against the gold labels. It says
nothing about real model quality: `make eval` with a real model does."""

from collections import Counter

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import Chunk
from app.db.session import SessionMaker
from app.llm.embedder import FakeEmbedder
from benchmark.oracle import OracleLLM
from benchmark.run import evaluate, prepare, summarize
from benchmark.schema import load_items
from seeds.data import BUSINESSES


def test_dataset_is_valid_and_covers_what_phase_1_needs() -> None:
    items = load_items()
    assert len(items) >= 350
    assert {i.language for i in items} == {"en", "hi", "gu", "hinglish", "gujlish"}
    assert {i.vertical for i in items} == {"printing", "photography"}
    assert Counter(i.intent.value for i in items)["pricing"] >= 120
    assert {sku for i in items for sku in i.expect.skus} == {
        item.sku for b in BUSINESSES.values() for item in b.items
    }  # every catalogue item has a question
    assert sum(1 for i in items if i.note == "injection") >= 20
    # every intent the router can return is exercised at least a few times
    assert Counter(i.intent.value for i in items).keys() >= {
        "greeting", "order_followup", "availability", "complaint", "negotiation", "spam",
    }  # fmt: skip
    assert all(
        sum(1 for i in items if i.language == lang) >= 50
        for lang in ("en", "hinglish", "hi", "gujlish", "gu")
    )
    assert sum(1 for i in items if i.handoff) >= 40
    assert sum(1 for i in items if not i.expect.grounded and not i.handoff) >= 10


def test_every_expected_price_and_sku_exists_in_the_seed_catalogue() -> None:
    catalogue = {i.sku: i.base_price_paise for b in BUSINESSES.values() for i in b.items}
    faqs = {q for b in BUSINESSES.values() for q, _ in b.faqs}
    for item in load_items():
        assert set(item.expect.skus) <= set(catalogue), item.id
        for sku in item.expect.skus:
            if item.intent.value == "pricing" and item.expect.grounded:
                assert catalogue[sku] in item.expect.price_paise, item.id
        if item.expect.faq:
            assert item.expect.faq in faqs, item.id


class OtherEmbedder(FakeEmbedder):
    """A different embedder: same text, different vector."""

    def _one(self, text: str) -> list[float]:
        return super()._one(text + "!")


async def test_switching_embedder_re_embeds_instead_of_searching_stale_vectors(
    sessionmaker: SessionMaker, settings: Settings
) -> None:
    llm = OracleLLM()
    contexts = await prepare(sessionmaker, settings, FakeEmbedder(), llm)
    ctx = contexts["printing"]
    async with sessionmaker() as session:
        before = (
            await session.execute(select(Chunk.embedding).where(Chunk.tenant_id == ctx.tenant_id))
        ).first()
    await prepare(sessionmaker, settings, OtherEmbedder(), llm)
    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(Chunk.content, Chunk.embedding).where(Chunk.tenant_id == ctx.tenant_id)
            )
        ).all()
    assert before is not None and rows
    expected = await OtherEmbedder().embed([rows[0][0]])
    assert list(rows[0][1]) == pytest.approx(expected[0])  # the new embedder's vector, not the old


@pytest.mark.parametrize("include_semantic", [False])
async def test_harness_with_oracle_meets_the_phase_1_gates(
    sessionmaker: SessionMaker, settings: Settings, include_semantic: bool
) -> None:
    outcomes = await evaluate(
        sessionmaker,
        settings,
        FakeEmbedder(),
        OracleLLM(),
        load_items(),
        include_semantic=include_semantic,
    )
    summary = summarize(outcomes, oracle=True)
    failures = [
        (o.item.id, o.item.text, o.reply)
        for o in outcomes
        if False in (o.handoff_ok, o.grounded_ok, o.retrieval_ok, o.price_ok)
    ]
    assert not failures, failures
    assert summary["hallucinated_amounts"] == 0
    assert summary["price_accuracy"] == 100.0
    assert summary["handoff_accuracy"] == 100.0
    assert len(outcomes) >= 250  # the semantic (multilingual-embedding) items are skipped here
