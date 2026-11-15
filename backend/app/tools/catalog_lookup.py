"""Catalogue lookup for the Knowledge agent. The ONLY source of prices in a customer reply."""

import uuid
from dataclasses import dataclass

from app.db.models import CatalogItem
from app.llm.embedder import Embedder
from app.repositories.catalog import CatalogRepository
from app.tools.search import build_tsquery, rrf


@dataclass(frozen=True)
class CatalogHit:
    item_id: uuid.UUID
    sku: str
    name: str
    unit: str
    base_price_paise: int
    gst_rate: int
    stock_status: str
    description: str | None
    match: str  # which strategy found it: sku | alias | fuzzy | search


def _hit(item: CatalogItem, match: str) -> CatalogHit:
    return CatalogHit(
        item.id,
        item.sku,
        item.name,
        item.unit,
        item.base_price_paise,
        item.gst_rate,
        item.stock_status.value,
        item.description,
        match,
    )


async def lookup_catalog(
    repo: CatalogRepository,
    embedder: Embedder,
    terms: list[str],
    max_distance: float,
    limit: int = 5,
) -> list[CatalogHit]:
    """Per term, the first strategy that finds anything wins: exact SKU, then exact alias/name,
    then fuzzy trigram match, then hybrid (vector + full-text) search."""
    found: dict[uuid.UUID, CatalogHit] = {}
    for term in dict.fromkeys(t.strip() for t in terms if t.strip()):
        for hit in await _lookup_one(repo, embedder, term, limit, max_distance):
            found.setdefault(hit.item_id, hit)
        if len(found) >= limit:
            break
    return list(found.values())[:limit]


async def _lookup_one(
    repo: CatalogRepository, embedder: Embedder, term: str, limit: int, max_distance: float
) -> list[CatalogHit]:
    if (item := await repo.by_sku(term)) is not None:
        return [_hit(item, "sku")]
    if items := await repo.by_alias(term):
        return [_hit(i, "alias") for i in items]
    if items := await repo.by_trigram(term, limit):
        return [_hit(i, "fuzzy") for i in items]
    (vector,) = await embedder.embed([term])
    by_vector = await repo.by_vector(vector, limit * 2, max_distance)
    tsquery = build_tsquery(term)
    by_text = await repo.by_text(tsquery, limit * 2) if tsquery else []
    return [_hit(i, "search") for i in rrf([by_vector, by_text], key=lambda i: i.id)[:limit]]
