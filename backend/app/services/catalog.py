import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import ConflictError, NotFoundError
from app.db.models import CatalogItem
from app.jobs.queue import enqueue
from app.repositories.catalog import (
    CatalogRepository,
    CatalogRow,
    build_search_text,
    normalize_aliases,
)
from app.schemas.catalog import CatalogItemCreate, CatalogItemUpdate


class CatalogService:
    """Hand-edits to single catalogue items (bulk changes go through the import flow)."""

    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx
        self._repo = CatalogRepository(session, ctx)

    async def create(self, data: CatalogItemCreate) -> CatalogItem:
        if await self._repo.by_sku(data.sku, active_only=False) is not None:
            raise ConflictError("An item with this SKU already exists")
        item = await self._repo.add_one(
            CatalogRow(
                sku=data.sku.strip(),
                name=data.name.strip(),
                base_price_paise=data.base_price_paise,
                aliases=data.aliases,
                category=data.category,
                description=data.description,
                unit=data.unit,
                gst_rate=data.gst_rate,
                hsn_sac=data.hsn_sac,
                stock_status=data.stock_status,
            )
        )
        await enqueue(self._session, self._ctx, "embed_catalog_items")
        return item

    async def update(self, item_id: uuid.UUID, data: CatalogItemUpdate) -> CatalogItem:
        item = await self._repo.get(item_id)
        if item is None:
            raise NotFoundError("Item not found")
        for field_name, value in data.model_dump(exclude_unset=True).items():
            if field_name == "aliases":
                value = normalize_aliases(value or [])
            setattr(item, field_name, value)
        item.search_text = build_search_text(
            item.name, item.aliases, item.category, item.description
        )
        item.embedding = None  # name, aliases or description may have changed: re-embed
        await enqueue(self._session, self._ctx, "embed_catalog_items")
        return item

    async def delete(self, item_id: uuid.UUID) -> None:
        item = await self._repo.get(item_id)
        if item is None:
            raise NotFoundError("Item not found")
        await self._repo.delete(item)
