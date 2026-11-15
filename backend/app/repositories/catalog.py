import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import CatalogItem, StockStatus

_BATCH = 500


def normalize_aliases(aliases: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for alias in aliases:
        cleaned = " ".join(alias.lower().split())
        if cleaned:
            seen[cleaned] = None
    return list(seen)


def build_search_text(
    name: str, aliases: list[str], category: str | None, description: str | None
) -> str:
    return " ".join(part for part in (name, *aliases, category, description) if part)


@dataclass(frozen=True)
class CatalogRow:
    sku: str
    name: str
    base_price_paise: int
    aliases: list[str] = field(default_factory=list)
    category: str | None = None
    description: str | None = None
    unit: str = "unit"
    gst_rate: int = 18
    hsn_sac: str | None = None
    stock_status: StockStatus = StockStatus.NA
    attributes: dict[str, Any] = field(default_factory=dict)

    def values(self) -> dict[str, Any]:
        aliases = normalize_aliases(self.aliases)
        return {
            "sku": self.sku,
            "name": self.name,
            "aliases": aliases,
            "category": self.category,
            "description": self.description,
            "unit": self.unit,
            "base_price_paise": self.base_price_paise,
            "gst_rate": self.gst_rate,
            "hsn_sac": self.hsn_sac,
            "stock_status": self.stock_status,
            "attributes": self.attributes,
            "search_text": build_search_text(self.name, aliases, self.category, self.description),
        }


class CatalogRepository:
    """Tenant-scoped. Lookup methods only ever return active items."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    def _mine(self, *extra: ColumnElement[bool]) -> ColumnElement[bool]:
        return and_(CatalogItem.tenant_id == self._ctx.tenant_id, *extra)

    async def upsert_many(self, rows: list[CatalogRow]) -> tuple[int, int]:
        """Insert or update by (tenant, sku). Changed rows lose their embedding so the worker
        re-embeds them. Returns (created, updated). Callers must pass unique SKUs."""
        created = updated = 0
        for start in range(0, len(rows), _BATCH):
            batch = [
                {**r.values(), "tenant_id": self._ctx.tenant_id, "id": uuid.uuid4()}
                for r in rows[start : start + _BATCH]
            ]
            values = insert(CatalogItem).values(batch)
            changes: dict[str, Any] = {
                k: getattr(values.excluded, k)
                for k in batch[0]
                if k not in ("id", "tenant_id", "sku")
            }
            changes |= {"embedding": None, "is_active": True, "updated_at": func.now()}
            statement: Any = values.on_conflict_do_update(
                index_elements=["tenant_id", "sku"], set_=changes
            ).returning(literal_column("(xmax = 0)"))
            for (inserted,) in await self._session.execute(statement):
                created += inserted
                updated += not inserted
        return created, updated

    async def add_one(self, row: CatalogRow) -> CatalogItem:
        await self.upsert_many([row])
        item = await self.by_sku(row.sku, active_only=False)
        if item is None:
            raise LookupError("upserted catalogue item not found")
        return item

    async def get(self, item_id: uuid.UUID) -> CatalogItem | None:
        return await self._session.scalar(
            select(CatalogItem).where(self._mine(CatalogItem.id == item_id))
        )

    async def browse(
        self, *, q: str | None = None, category: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[CatalogItem]:
        query = select(CatalogItem).where(self._mine())
        if q:
            like = f"%{q.lower()}%"
            query = query.where(
                or_(
                    func.lower(CatalogItem.sku).like(like),
                    func.lower(CatalogItem.search_text).like(like),
                )
            )
        if category:
            query = query.where(CatalogItem.category == category)
        result = await self._session.scalars(
            query.order_by(CatalogItem.name).limit(limit).offset(offset)
        )
        return list(result)

    async def by_ids(self, ids: list[uuid.UUID]) -> list[CatalogItem]:
        result = await self._session.scalars(
            select(CatalogItem).where(self._mine(CatalogItem.id.in_(ids)))
        )
        return list(result)

    async def delete(self, item: CatalogItem) -> None:
        await self._session.execute(
            delete(CatalogItem).where(self._mine(CatalogItem.id == item.id))
        )

    # --- embeddings -----------------------------------------------------------------------

    async def without_embedding(self, limit: int) -> list[CatalogItem]:
        result = await self._session.scalars(
            select(CatalogItem)
            .where(self._mine(CatalogItem.embedding.is_(None)))
            .order_by(CatalogItem.created_at)
            .limit(limit)
        )
        return list(result)

    async def set_embeddings(self, vectors: dict[uuid.UUID, list[float]]) -> None:
        for item_id, vector in vectors.items():
            await self._session.execute(
                update(CatalogItem)
                .where(self._mine(CatalogItem.id == item_id))
                .values(embedding=vector)
            )

    # --- lookups used by the Knowledge agent's catalog tool ---------------------------------

    def _live(self) -> ColumnElement[bool]:
        return self._mine(CatalogItem.is_active.is_(True))

    async def by_sku(self, sku: str, *, active_only: bool = True) -> CatalogItem | None:
        where = self._live() if active_only else self._mine()
        return await self._session.scalar(
            select(CatalogItem).where(where, func.lower(CatalogItem.sku) == sku.lower())
        )

    async def by_alias(self, term: str) -> list[CatalogItem]:
        cleaned = " ".join(term.lower().split())
        result = await self._session.scalars(
            select(CatalogItem).where(
                self._live(),
                or_(
                    CatalogItem.aliases.contains([cleaned]), func.lower(CatalogItem.name) == cleaned
                ),
            )
        )
        return list(result)

    async def by_trigram(self, term: str, limit: int, threshold: float = 0.4) -> list[CatalogItem]:
        similarity = func.word_similarity(term.lower(), CatalogItem.search_text)
        result = await self._session.scalars(
            select(CatalogItem)
            .where(self._live(), similarity >= threshold)
            .order_by(similarity.desc())
            .limit(limit)
        )
        return list(result)

    async def by_text(self, tsquery: str, limit: int) -> list[CatalogItem]:
        query = func.to_tsquery("simple", tsquery)
        result = await self._session.scalars(
            select(CatalogItem)
            .where(self._live(), CatalogItem.tsv.op("@@")(query))
            .order_by(func.ts_rank(CatalogItem.tsv, query).desc())
            .limit(limit)
        )
        return list(result)

    async def by_vector(
        self, vector: list[float], limit: int, max_distance: float
    ) -> list[CatalogItem]:
        distance = CatalogItem.embedding.cosine_distance(vector)
        result = await self._session.scalars(
            select(CatalogItem)
            .where(self._live(), CatalogItem.embedding.is_not(None), distance <= max_distance)
            .order_by(distance)
            .limit(limit)
        )
        return list(result)
