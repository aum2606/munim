from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request, UploadFile

from app.core.deps import Config, Context, Owner, Session
from app.ingestion.documents import DocumentService
from app.repositories.documents import DocumentRepository
from app.schemas.documents import DocumentView, FAQInput
from app.workers.queue import JobQueue

router = APIRouter()


def service(request: Request, session: Session, ctx: Owner, config: Config) -> DocumentService:
    return DocumentService(session, ctx, config, cast(JobQueue, request.app.state.jobs))


@router.post("/documents", response_model=DocumentView, status_code=201)
async def upload(
    file: UploadFile, request: Request, session: Session, ctx: Owner, config: Config
) -> DocumentView:
    return await service(request, session, ctx, config).upload(
        file.filename or "", await file.read(5 * 1024 * 1024 + 1)
    )


@router.get("/documents", response_model=list[DocumentView])
async def documents(ctx: Context, session: Session) -> list[DocumentView]:
    return [
        DocumentView.model_validate(document)
        for document in await DocumentRepository(session, ctx).list()
    ]


@router.get("/documents/{document_id}", response_model=DocumentView)
async def document(document_id: UUID, ctx: Context, session: Session) -> DocumentView:
    return DocumentView.model_validate(await DocumentRepository(session, ctx).get(document_id))


@router.post("/documents/{document_id}/retry", response_model=DocumentView)
async def retry(
    document_id: UUID, request: Request, session: Session, ctx: Owner, config: Config
) -> DocumentView:
    return await service(request, session, ctx, config).retry(document_id)


@router.post("/faqs", response_model=DocumentView, status_code=201)
async def faq(
    body: FAQInput, request: Request, session: Session, ctx: Owner, config: Config
) -> DocumentView:
    return await service(request, session, ctx, config).faq(body)
