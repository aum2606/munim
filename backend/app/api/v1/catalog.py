import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status

from app.core.deps import CtxDep, LLMDep, OwnerDep, SessionDep, SettingsDep
from app.db.models import CatalogItem
from app.ingestion.uploads import read_limited
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import (
    CatalogItemCreate,
    CatalogItemOut,
    CatalogItemUpdate,
    ImportCommitResult,
    ImportMappingUpdate,
    ImportPreview,
)
from app.services.catalog import CatalogService
from app.services.catalog_import import CatalogImportService, build_template

router = APIRouter(prefix="/catalog", tags=["catalog"])
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _import_service(
    ctx: OwnerDep, session: SessionDep, settings: SettingsDep, llm: LLMDep, request: Request
) -> CatalogImportService:
    return CatalogImportService(session, ctx, settings, llm, request.app.state.sessionmaker)


ImportDep = Annotated[CatalogImportService, Depends(_import_service, scope="function")]


@router.get("/template.xlsx")
async def template(_: CtxDep) -> Response:
    return Response(
        build_template(),
        media_type=_XLSX,
        headers={"Content-Disposition": 'attachment; filename="munim-catalogue-template.xlsx"'},
    )


@router.post("/import", response_model=ImportPreview, status_code=status.HTTP_201_CREATED)
async def start_import(
    file: Annotated[UploadFile, File()], service: ImportDep, settings: SettingsDep
) -> ImportPreview:
    content = await read_limited(file, settings.max_upload_mb)
    return await service.start(file.filename or "catalogue", content)


@router.get("/import/{job_id}", response_model=ImportPreview)
async def import_preview(job_id: uuid.UUID, service: ImportDep) -> ImportPreview:
    return await service.preview(job_id)


@router.patch("/import/{job_id}", response_model=ImportPreview)
async def import_set_mapping(
    job_id: uuid.UUID, body: ImportMappingUpdate, service: ImportDep
) -> ImportPreview:
    return await service.update_mapping(job_id, body.mapping)


@router.post("/import/{job_id}/commit", response_model=ImportCommitResult)
async def import_commit(job_id: uuid.UUID, service: ImportDep) -> ImportCommitResult:
    return await service.commit(job_id)


@router.get("/items", response_model=list[CatalogItemOut])
async def list_items(
    ctx: CtxDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CatalogItem]:
    return await CatalogRepository(session, ctx).browse(
        q=q, category=category, limit=limit, offset=offset
    )


@router.post("/items", response_model=CatalogItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(body: CatalogItemCreate, ctx: OwnerDep, session: SessionDep) -> CatalogItem:
    return await CatalogService(session, ctx).create(body)


@router.patch("/items/{item_id}", response_model=CatalogItemOut)
async def update_item(
    item_id: uuid.UUID, body: CatalogItemUpdate, ctx: OwnerDep, session: SessionDep
) -> CatalogItem:
    return await CatalogService(session, ctx).update(item_id, body)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: uuid.UUID, ctx: OwnerDep, session: SessionDep) -> None:
    await CatalogService(session, ctx).delete(item_id)
