"""Catalogue import: upload -> auto/LLM column mapping -> preview with row errors -> commit.

Nothing is written to the catalogue until the owner commits a previewed file, and rows with
problems are skipped and reported, never guessed at (especially prices).
"""

import csv
import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import structlog
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import TenantContext
from app.core.errors import (
    ConflictError,
    FileRejectedError,
    LLMOutputError,
    LLMUnavailableError,
    NotFoundError,
)
from app.db.models import ImportJob, ImportStatus, StockStatus
from app.db.session import SessionMaker
from app.ingestion.price_parser import parse_inr
from app.ingestion.uploads import read_upload, save_upload, sniff_spreadsheet
from app.jobs.queue import enqueue
from app.llm.base import LLMClient
from app.llm.prompting import render_prompt
from app.llm.recording import agent_run
from app.repositories.catalog import CatalogRepository, CatalogRow
from app.repositories.imports import ImportJobRepository
from app.schemas.catalog import (
    GST_RATES,
    ColumnMapping,
    ImportCommitResult,
    ImportPreview,
    ImportRowPreview,
)

log = structlog.get_logger()

MAX_ROWS = 5000
MAX_COLUMNS = 50
PREVIEW_ROWS = 25
REQUIRED = ("name", "price")
FIELDS = (
    "sku",
    "name",
    "aliases",
    "category",
    "description",
    "unit",
    "price",
    "gst_rate",
    "hsn_sac",
    "stock_status",
)
TEMPLATE_HEADERS = list(FIELDS)

_SYNONYMS: dict[str, set[str]] = {
    "sku": {"sku", "code", "item code", "product code", "id", "item id"},
    "name": {"name", "item", "item name", "product", "product name", "particulars", "service"},
    "aliases": {"aliases", "alias", "also called", "other names", "synonyms"},
    "category": {"category", "type", "group", "department"},
    "description": {"description", "details", "desc", "notes", "remarks"},
    "unit": {"unit", "uom", "per", "unit of measure"},
    "price": {
        "price",
        "rate",
        "mrp",
        "selling price",
        "cost",
        "amount",
        "base price",
        "unit price",
    },
    "gst_rate": {"gst", "gst rate", "gst %", "gst%", "tax", "tax rate"},
    "hsn_sac": {"hsn", "sac", "hsn/sac", "hsn code", "sac code", "hsn sac"},
    "stock_status": {"stock", "stock status", "availability", "status"},
}
_STOCK_WORDS = {
    "in_stock": {"in stock", "in_stock", "yes", "available", "y"},
    "out_of_stock": {"out of stock", "out_of_stock", "no", "unavailable", "n"},
    "on_order": {"on order", "on_order", "order", "made to order"},
    "na": {"", "na", "n/a", "-"},
}


def _normalize(header: str) -> str:
    return re.sub(r"[\s_]+", " ", header.strip().lower())


def auto_map(headers: list[str]) -> dict[str, str]:
    """Exact (case-insensitive) header-name matches against known synonyms."""
    mapping: dict[str, str] = {}
    for header in headers:
        for field_name, names in _SYNONYMS.items():
            if field_name not in mapping and _normalize(header) in names:
                mapping[field_name] = header
                break
    return mapping


def read_table(content: bytes, kind: str) -> tuple[list[str], list[list[str]]]:
    """Header row and data rows as strings, from an .xlsx (first sheet) or a CSV."""
    try:
        raw = _xlsx_rows(content) if kind == "xlsx" else _csv_rows(content)
    except Exception as exc:  # corrupt or hostile file: report, never crash the request
        log.warning("spreadsheet_unreadable", error=type(exc).__name__)
        raise FileRejectedError("The file could not be read as a spreadsheet") from exc
    if not raw or not any(c.strip() for c in raw[0]):
        raise FileRejectedError("The first row must contain column headers")
    width = min(len(raw[0]), MAX_COLUMNS)
    headers = [h.strip() for h in raw[0][:width]]
    if len({_normalize(h) for h in headers if h}) != len([h for h in headers if h]):
        raise FileRejectedError("Column headers must be unique")
    rows = [(r + [""] * width)[:width] for r in raw[1 : MAX_ROWS + 1]]
    return headers, [r for r in rows if any(c.strip() for c in r)]


def _xlsx_rows(content: bytes) -> list[list[str]]:
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    return [
        ["" if v is None else str(v) for v in row]
        for row in sheet.iter_rows(max_row=MAX_ROWS + 1, max_col=MAX_COLUMNS, values_only=True)
    ]


def _csv_rows(content: bytes) -> list[list[str]]:
    text = content.decode("utf-8-sig")
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(
            text[:2048], delimiters=",;\t"
        )
    except csv.Error:
        dialect = csv.excel
    return [
        row
        for _, row in zip(range(MAX_ROWS + 2), csv.reader(io.StringIO(text), dialect), strict=False)
    ]


@dataclass
class _Parsed:
    number: int
    row: CatalogRow | None
    values: dict[str, Any]
    errors: list[str]


def _stock(value: str) -> StockStatus | None:
    cleaned = value.strip().lower()
    for status, words in _STOCK_WORDS.items():
        if cleaned in words:
            return StockStatus(status)
    return None


def parse_rows(headers: list[str], rows: list[list[str]], mapping: dict[str, str]) -> list[_Parsed]:
    """Validate every row against the mapping. Row numbers are spreadsheet rows (header = 1)."""
    column = {field_name: headers.index(h) for field_name, h in mapping.items() if h in headers}
    mapped_columns = set(column.values())
    seen_skus: set[str] = set()
    parsed: list[_Parsed] = []
    for offset, cells in enumerate(rows):

        def get(field_name: str, cells: list[str] = cells) -> str:
            return cells[column[field_name]].strip() if field_name in column else ""

        errors: list[str] = []
        name = get("name")
        if not name:
            errors.append("name is missing")
        elif len(name) > 200:
            errors.append("name is longer than 200 characters")
        price = 0
        try:
            price = parse_inr(get("price"))
        except ValueError:
            errors.append(f"price {get('price')!r} is not a valid amount")
        gst = 18
        if get("gst_rate"):
            try:
                rate = Decimal(get("gst_rate").rstrip("%").strip())
                gst = int(rate) if rate == rate.to_integral_value() else -1
            except InvalidOperation:
                gst = -1
            if gst not in GST_RATES:
                errors.append(
                    f"GST rate {get('gst_rate')!r} must be one of {', '.join(map(str, GST_RATES))}"
                )
        stock = _stock(get("stock_status"))
        if stock is None:
            errors.append(f"stock status {get('stock_status')!r} is not recognised")
        sku = get("sku")[:64] or "auto-" + hashlib.sha1(name.lower().encode()).hexdigest()[:10]  # noqa: S324
        if sku.lower() in seen_skus:
            errors.append(f"duplicate SKU {sku!r} earlier in the file")
        attributes = {
            headers[i][:60]: cells[i].strip()[:200]
            for i in range(len(headers))
            if i not in mapped_columns and headers[i] and cells[i].strip()
        }
        values: dict[str, Any] = {"sku": sku, "name": name, "price_paise": price, "gst_rate": gst}
        row = None
        if not errors:
            seen_skus.add(sku.lower())
            row = CatalogRow(
                sku=sku,
                name=name,
                base_price_paise=price,
                aliases=[a for a in re.split(r"[,;|]", get("aliases")) if a.strip()],
                category=get("category")[:80] or None,
                description=get("description")[:2000] or None,
                unit=get("unit")[:24] or "unit",
                gst_rate=gst,
                hsn_sac=get("hsn_sac")[:16] or None,
                stock_status=stock or StockStatus.NA,
                attributes=dict(list(attributes.items())[:20]),
            )
        parsed.append(_Parsed(offset + 2, row, values, errors))
    return parsed


def build_template() -> bytes:
    workbook = Workbook()
    sheet = cast(Worksheet, workbook.active)
    sheet.title = "Catalogue"
    sheet.append(TEMPLATE_HEADERS)
    sheet.append(
        [
            "EXAMPLE-1",
            "Visiting card (100 pcs)",
            "business card, name card",
            "Printing",
            "Matt finish, 300 gsm",
            "per 100",
            250,
            18,
            "4911",
            "in stock",
        ]
    )
    sheet.append(
        [
            "EXAMPLE-2",
            "Flex banner",
            "hoarding",
            "Printing",
            "",
            "per sq ft",
            "₹18/-",
            18,
            "3926",
            "in stock",
        ]
    )
    notes = workbook.create_sheet("Read me")
    for line in (
        "Replace the two EXAMPLE rows with your own items, then upload this file.",
        "Required: name and price. Everything else is optional.",
        "price accepts 450, 1,20,000, 1.2L, 45k, Rs. 450 or ₹450/-.",
        "gst_rate must be 0, 5, 12, 18 or 28 (18 is used if blank).",
        "stock_status: in stock, out of stock, on order, or leave blank.",
        "Any extra columns you add are kept as notes on the item.",
    ):
        notes.append([line])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class CatalogImportService:
    def __init__(
        self,
        session: AsyncSession,
        ctx: TenantContext,
        settings: Settings,
        llm: LLMClient | None,
        sessionmaker: SessionMaker,
    ) -> None:
        self._session = session
        self._ctx = ctx
        self._settings = settings
        self._llm = llm
        self._sessionmaker = sessionmaker
        self._jobs = ImportJobRepository(session, ctx)
        self._catalog = CatalogRepository(session, ctx)

    async def start(self, filename: str, content: bytes) -> ImportPreview:
        kind = sniff_spreadsheet(content)
        headers, rows = read_table(content, kind)
        mapping = auto_map(headers)
        if any(f not in mapping for f in REQUIRED):
            guessed = await self._llm_map(headers, rows)
            taken = set(mapping.values())  # a column already matched by name is not up for grabs
            mapping |= {f: h for f, h in guessed.items() if f not in mapping and h not in taken}
        path = save_upload(self._settings.storage_dir, self._ctx.tenant_id, content, kind)
        job = await self._jobs.add(
            filename=filename,
            storage_path=path,
            headers=headers,
            mapping=mapping,
            row_count=len(rows),
        )
        return self._preview(job, rows)

    async def update_mapping(self, job_id: uuid.UUID, mapping: dict[str, str]) -> ImportPreview:
        job = await self._load(job_id)
        if any(f not in FIELDS or h not in job.headers for f, h in mapping.items()):
            raise FileRejectedError("Mapping refers to an unknown field or column")
        if len(set(mapping.values())) != len(mapping):
            raise FileRejectedError("Two fields cannot use the same column")
        job.mapping = mapping
        return self._preview(job, self._rows(job))

    async def preview(self, job_id: uuid.UUID) -> ImportPreview:
        job = await self._load(job_id)
        return self._preview(job, self._rows(job))

    async def commit(self, job_id: uuid.UUID) -> ImportCommitResult:
        job = await self._load(job_id)
        if job.status == ImportStatus.COMMITTED:
            raise ConflictError("This import was already saved")
        if missing := [f for f in REQUIRED if f not in job.mapping]:
            raise FileRejectedError(f"Choose a column for: {', '.join(missing)}")
        parsed = parse_rows(job.headers, self._rows(job), job.mapping)
        good = [p.row for p in parsed if p.row is not None]
        created, updated = await self._catalog.upsert_many(good)
        self._jobs.mark_committed(job)
        await enqueue(self._session, self._ctx, "embed_catalog_items")
        return ImportCommitResult(created=created, updated=updated, skipped=len(parsed) - len(good))

    # ---------------------------------------------------------------------------------------

    async def _load(self, job_id: uuid.UUID) -> ImportJob:
        job = await self._jobs.get(job_id)
        if job is None:
            raise NotFoundError("Import not found")
        return job

    def _rows(self, job: ImportJob) -> list[list[str]]:
        content = read_upload(self._settings.storage_dir, job.storage_path)
        return read_table(content, sniff_spreadsheet(content))[1]

    def _preview(self, job: ImportJob, rows: list[list[str]]) -> ImportPreview:
        parsed = parse_rows(job.headers, rows, job.mapping)
        bad = [p for p in parsed if p.errors]
        shown = (bad + [p for p in parsed if not p.errors])[:PREVIEW_ROWS]
        return ImportPreview(
            job_id=job.id,
            filename=job.filename,
            status=job.status.value,
            headers=job.headers,
            mapping=job.mapping,
            missing_required=[f for f in REQUIRED if f not in job.mapping],
            row_count=len(parsed),
            valid_count=len(parsed) - len(bad),
            error_count=len(bad),
            rows=[
                ImportRowPreview(row=p.number, values=p.values, errors=p.errors)
                for p in sorted(shown, key=lambda p: p.number)
            ],
        )

    async def _llm_map(self, headers: list[str], rows: list[list[str]]) -> dict[str, str]:
        """Ask the model to map the columns we could not match by name. Best effort: on any
        failure the owner simply picks the columns in the preview screen."""
        if self._llm is None:
            return {}
        messages, version = render_prompt("column_mapper", headers=headers, sample_rows=rows[:3])
        try:
            async with agent_run(
                self._sessionmaker,
                self._ctx,
                agent="column_mapper",
                prompt_version=version,
                input={"headers": headers},
            ) as run:
                result, run.result = await self._llm.structured("small", messages, ColumnMapping)
                run.output = result.model_dump()
        except (LLMUnavailableError, LLMOutputError):
            return {}
        used: set[str] = set()
        valid: dict[str, str] = {}
        for field_name, header in result.mapping.items():  # never trust the model's output blindly
            if field_name in FIELDS and header in headers and header not in used:
                valid[field_name] = header
                used.add(header)
        return valid
