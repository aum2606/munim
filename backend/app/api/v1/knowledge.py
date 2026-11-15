import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.core.deps import CtxDep, OwnerDep, SessionDep, SettingsDep
from app.db.models import Document, GapStatus, KnowledgeGap
from app.ingestion.uploads import read_limited
from app.repositories.documents import DocumentRepository
from app.repositories.gaps import KnowledgeGapRepository
from app.schemas.knowledge import DocumentOut, FaqIn, FaqOut, GapAnswer, GapOut
from app.services.documents import DocumentService

router = APIRouter(tags=["knowledge"])


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(ctx: CtxDep, session: SessionDep) -> list[Document]:
    return await DocumentRepository(session, ctx).browse(faq=False)


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: Annotated[UploadFile, File()],
    ctx: OwnerDep,
    session: SessionDep,
    settings: SettingsDep,
    title: Annotated[str | None, Form(max_length=200)] = None,
) -> Document:
    content = await read_limited(file, settings.max_upload_mb)
    return await DocumentService(session, ctx, settings).upload(
        title, file.filename or "document", content
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> None:
    await DocumentService(session, ctx, settings).delete(document_id)


@router.get("/faqs", response_model=list[FaqOut])
async def list_faqs(ctx: CtxDep, session: SessionDep) -> list[FaqOut]:
    repo = DocumentRepository(session, ctx)
    documents = await repo.browse(faq=True)
    texts = await repo.first_chunk_texts([d.id for d in documents])
    return [
        FaqOut(
            id=d.id,
            question=d.title,
            answer=texts.get(d.id, "").split("\nA: ", 1)[-1],
            status=d.status,
        )
        for d in documents
    ]


def _faq_out(document: Document, answer: str) -> FaqOut:
    return FaqOut(id=document.id, question=document.title, answer=answer, status=document.status)


@router.post("/faqs", response_model=FaqOut, status_code=status.HTTP_201_CREATED)
async def create_faq(
    body: FaqIn, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> FaqOut:
    service = DocumentService(session, ctx, settings)
    return _faq_out(await service.create_faq(body.question, body.answer), body.answer)


@router.put("/faqs/{faq_id}", response_model=FaqOut)
async def update_faq(
    faq_id: uuid.UUID, body: FaqIn, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> FaqOut:
    service = DocumentService(session, ctx, settings)
    return _faq_out(await service.update_faq(faq_id, body.question, body.answer), body.answer)


@router.delete("/faqs/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    faq_id: uuid.UUID, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> None:
    await DocumentService(session, ctx, settings).delete(faq_id)


@router.get("/knowledge-gaps", response_model=list[GapOut])
async def list_gaps(
    ctx: CtxDep,
    session: SessionDep,
    status_filter: Annotated[GapStatus | None, Query(alias="status")] = None,
) -> list[KnowledgeGap]:
    return await KnowledgeGapRepository(session, ctx).browse(status_filter)


@router.post("/knowledge-gaps/{gap_id}/answer", response_model=GapOut)
async def answer_gap(
    gap_id: uuid.UUID, body: GapAnswer, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> KnowledgeGap:
    return await DocumentService(session, ctx, settings).answer_gap(gap_id, body.answer)


@router.post("/knowledge-gaps/{gap_id}/ignore", response_model=GapOut)
async def ignore_gap(gap_id: uuid.UUID, ctx: OwnerDep, session: SessionDep) -> KnowledgeGap:
    return await KnowledgeGapRepository(session, ctx).ignore(gap_id)
