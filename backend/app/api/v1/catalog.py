from uuid import UUID

from fastapi import APIRouter, Request, Response, UploadFile
from sqlalchemy.exc import IntegrityError

from app.core.deps import Config, Context, Owner, Session
from app.core.errors import DomainError
from app.ingestion.catalog import CatalogImportService
from app.ingestion.catalog_files import template_xlsx
from app.llm.factory import make_embedder, make_llm
from app.repositories.agent_runs import DatabaseRunRecorder
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import CatalogInput, CatalogView, ImportCommit, ImportView

router = APIRouter(prefix="/catalog")


def service(request: Request, session: Session, ctx: Owner, config: Config) -> CatalogImportService:
    return CatalogImportService(
        session,
        ctx,
        make_llm(config, DatabaseRunRecorder(request.app.state.sessions)),
        make_embedder(config),
    )


@router.get("/template.xlsx")
async def template(ctx: Context) -> Response:
    return Response(
        template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="munim-catalogue.xlsx"'},
    )


@router.post("/import", response_model=ImportView, status_code=201)
async def upload_catalog(
    file: UploadFile, request: Request, session: Session, ctx: Owner, config: Config
) -> ImportView:
    return await service(request, session, ctx, config).upload(
        file.filename or "", await file.read(5 * 1024 * 1024 + 1)
    )


@router.get("/import/{import_id}", response_model=ImportView)
async def get_import(
    import_id: UUID, request: Request, session: Session, ctx: Owner, config: Config
) -> ImportView:
    return await service(request, session, ctx, config).get(import_id)


@router.post("/import/{import_id}/commit", response_model=ImportView)
async def commit_import(
    import_id: UUID,
    body: ImportCommit,
    request: Request,
    session: Session,
    ctx: Owner,
    config: Config,
) -> ImportView:
    return await service(request, session, ctx, config).commit(import_id, body.mapping)


@router.get("/items", response_model=list[CatalogView])
async def items(ctx: Context, session: Session) -> list[CatalogView]:
    return [
        CatalogView.model_validate(catalog)
        for catalog in await CatalogRepository(session, ctx).list()
    ]


@router.get("/items/{catalog_id}", response_model=CatalogView)
async def item(catalog_id: UUID, ctx: Context, session: Session) -> CatalogView:
    return CatalogView.model_validate(await CatalogRepository(session, ctx).get(catalog_id))


@router.put("/items/{catalog_id}", response_model=CatalogView)
async def update_item(
    catalog_id: UUID, body: CatalogInput, ctx: Owner, session: Session, config: Config
) -> CatalogView:
    # Editing prices is an explicit owner action; model-generated prices are never accepted.
    vector = (await make_embedder(config).embed([body.name + " " + body.description]))[0]
    try:
        catalog = await CatalogRepository(session, ctx).update(catalog_id, body, vector)
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise DomainError("SKU already exists or catalogue values are invalid", 409) from error
    return CatalogView.model_validate(catalog)


@router.delete("/items/{catalog_id}", status_code=204)
async def delete_item(catalog_id: UUID, ctx: Owner, session: Session) -> Response:
    catalog = await CatalogRepository(session, ctx).get(catalog_id)
    catalog.is_active = False
    await session.commit()
    return Response(status_code=204)
