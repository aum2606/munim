from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models import CatalogItem, Chunk, Document
from app.db.models.knowledge import DocumentStatus


def reciprocal_rank_fusion(rankings: list[list[UUID]], limit: int) -> list[UUID]:
    scores: dict[UUID, float] = defaultdict(float)
    for ranking in rankings:
        for rank, resource_id in enumerate(dict.fromkeys(ranking), 1):
            scores[resource_id] += 1 / (60 + rank)
    return sorted(scores, key=lambda resource_id: (-scores[resource_id], str(resource_id)))[:limit]


class SearchRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def knowledge(self, query: str, vector: list[float], limit: int = 5) -> list[Chunk]:
        root = (
            select(Chunk)
            .join(
                Document,
                (Chunk.tenant_id == Document.tenant_id) & (Chunk.document_id == Document.id),
            )
            .where(
                Chunk.tenant_id == self.ctx.tenant_id,
                Document.tenant_id == self.ctx.tenant_id,
                Document.status == DocumentStatus.READY,
            )
        )
        tsquery = func.websearch_to_tsquery("simple", query)
        lexical = (
            list(
                await self.session.scalars(
                    root.where(Chunk.tsv.op("@@")(tsquery))
                    .order_by(func.ts_rank_cd(Chunk.tsv, tsquery).desc(), Chunk.id)
                    .limit(limit * 3)
                )
            )
            if query
            else []
        )
        distance = Chunk.embedding.cosine_distance(vector)
        semantic = list(
            await self.session.scalars(
                root.where(distance <= 0.45).order_by(distance, Chunk.id).limit(limit * 3)
            )
        )
        found = {chunk.id: chunk for chunk in lexical + semantic}
        return [
            found[resource_id]
            for resource_id in reciprocal_rank_fusion(
                [[chunk.id for chunk in lexical], [chunk.id for chunk in semantic]], limit
            )
        ]

    async def catalog(self, query: str, vector: list[float], limit: int = 5) -> list[CatalogItem]:
        root = select(CatalogItem).where(
            CatalogItem.tenant_id == self.ctx.tenant_id, CatalogItem.is_active.is_(True)
        )
        exact = list(
            await self.session.scalars(
                root.where(func.lower(CatalogItem.sku) == query.lower()).limit(1)
            )
        )
        if exact:
            return exact
        aliases = list(
            await self.session.scalars(
                root.where(CatalogItem.aliases.contains([query])).limit(limit)
            )
        )
        if aliases:
            return aliases
        tsquery = func.websearch_to_tsquery("simple", query)
        rank = func.greatest(
            func.similarity(func.lower(CatalogItem.name), query),
            func.word_similarity(query, func.lower(CatalogItem.name)),
        )
        lexical = (
            list(
                await self.session.scalars(
                    root.where(or_(CatalogItem.tsv.op("@@")(tsquery), rank >= 0.4))
                    .order_by(rank.desc(), CatalogItem.id)
                    .limit(limit * 3)
                )
            )
            if query
            else []
        )
        distance = CatalogItem.embedding.cosine_distance(vector)
        semantic = list(
            await self.session.scalars(
                root.where(distance <= 0.45).order_by(distance, CatalogItem.id).limit(limit * 3)
            )
        )
        found = {catalog.id: catalog for catalog in lexical + semantic}
        return [
            found[resource_id]
            for resource_id in reciprocal_rank_fusion(
                [[catalog.id for catalog in lexical], [catalog.id for catalog in semantic]], limit
            )
        ]
