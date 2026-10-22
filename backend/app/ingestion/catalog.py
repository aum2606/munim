from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.db.models import CatalogImport
from app.db.models.knowledge import StockStatus
from app.ingestion.catalog_files import HEADERS, read_table
from app.ingestion.price_parser import parse_inr
from app.llm import Embedder, LLMClient
from app.llm.types import LLMRequest
from app.repositories.catalog import CatalogRepository
from app.repositories.scoped import ScopedRepository
from app.schemas.catalog import CatalogInput, ImportRow, ImportView, MappingInput, MappingOutput


class CatalogImportService:
    def __init__(
        self, session: AsyncSession, ctx: TenantContext, llm: LLMClient, embedder: Embedder
    ) -> None:
        self.session, self.ctx, self.llm, self.embedder = session, ctx, llm, embedder
        self.imports = ScopedRepository(session, ctx, CatalogImport)

    async def upload(self, filename: str, content: bytes) -> ImportView:
        headers, rows = read_table(filename, content)
        if set(HEADERS).issubset(headers):
            mapping = {field: field for field in HEADERS}
        else:
            env = Environment(
                loader=FileSystemLoader(Path(__file__).parents[1] / "agents" / "prompts"),
                undefined=StrictUndefined,
            )
            proposal = await self.llm.structured(
                self.ctx,
                LLMRequest(
                    agent="column_mapper",
                    system=env.get_template("column_mapper.jinja").render(),
                    content=MappingInput(headers=headers),
                    output_schema=MappingOutput.model_json_schema(),
                ),
                MappingOutput,
            )
            mapping = {binding.field: binding.column for binding in proposal.bindings}
        self._validate_mapping(headers, mapping)
        imported = await self.imports.create(headers=headers, rows=rows, mapping=mapping)
        await self.session.commit()
        return self.preview(imported, mapping)

    def _validate_mapping(self, headers: list[str], mapping: dict[str, str]) -> None:
        if (
            not {"sku", "name", "price"}.issubset(mapping)
            or not set(mapping).issubset(HEADERS)
            or not set(mapping.values()).issubset(headers)
        ):
            raise DomainError("Mapping must include sku, name and price using existing columns")
        if len(set(mapping.values())) != len(mapping):
            raise DomainError("Map each column only once")

    def preview(self, imported: CatalogImport, mapping: dict[str, str]) -> ImportView:
        self._validate_mapping(imported.headers, mapping)
        validated = []
        seen: set[str] = set()
        for number, row in enumerate(imported.rows, 2):
            fields = {field: row[column].strip() for field, column in mapping.items()}
            try:
                gst = Decimal(fields.get("gst_rate", "18") or "18")
                if gst not in {0, 5, 12, 18, 28}:
                    raise DomainError("GST rate must be 0, 5, 12, 18 or 28")
                catalog = CatalogInput(
                    sku=fields["sku"],
                    name=fields["name"],
                    base_price_paise=parse_inr(fields["price"]),
                    gst_rate=int(gst),
                    aliases=[
                        alias.strip()
                        for alias in fields.get("aliases", "").split("|")
                        if alias.strip()
                    ],
                    category=fields.get("category", "") or "general",
                    description=fields.get("description", ""),
                    unit=fields.get("unit", "") or "piece",
                    hsn_sac=fields.get("hsn_sac", ""),
                    stock_status=StockStatus(fields.get("stock_status", "") or "na"),
                )
                if catalog.sku in seen:
                    raise DomainError("Duplicate SKU within import")
                seen.add(catalog.sku)
                validated.append(ImportRow(number=number, catalog=catalog, errors=[]))
            except (DomainError, ValidationError, ValueError, InvalidOperation) as error:
                reason = (
                    error.message if isinstance(error, DomainError) else "Invalid catalogue fields"
                )
                validated.append(ImportRow(number=number, catalog=None, errors=[reason]))
        return ImportView(
            id=imported.id,
            headers=imported.headers,
            mapping=mapping,
            rows=validated,
            committed=imported.committed,
        )

    async def get(self, import_id: UUID) -> ImportView:
        imported = await self.imports.get(import_id)
        return self.preview(imported, imported.mapping)

    async def commit(self, import_id: UUID, mapping: dict[str, str]) -> ImportView:
        imported = await self.imports.get(import_id, for_update=True)
        if imported.committed:
            raise DomainError("Import has already been committed", 409)
        preview = self.preview(imported, mapping)
        if not preview.rows or any(row.errors for row in preview.rows):
            raise DomainError("Resolve all preview errors before committing")
        catalogs = [row.catalog for row in preview.rows if row.catalog is not None]
        vectors = await self.embedder.embed(
            [
                catalog.name + " " + " ".join(catalog.aliases) + " " + catalog.description
                for catalog in catalogs
            ]
        )
        for catalog, vector in zip(catalogs, vectors, strict=True):
            await CatalogRepository(self.session, self.ctx).upsert(catalog, vector)
        imported.mapping = mapping
        imported.committed = True
        await self.session.commit()
        preview.committed = True
        return preview
