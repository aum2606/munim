from uuid import UUID

from fastapi import APIRouter, Response

from app.core.deps import Config, Context, Session
from app.db.models.quote import QuoteStatus
from app.quotes.service import QuoteService
from app.repositories.quotes import QuoteRepository
from app.schemas.quotes import QuoteView

router = APIRouter(prefix="/quotes")


@router.get("", response_model=list[QuoteView])
async def quotes(
    session: Session, ctx: Context, config: Config, status: QuoteStatus | None = None
) -> list[QuoteView]:
    service = QuoteService(session, ctx, config)
    return [
        await service.view(quote.id)
        for quote in await QuoteRepository(session, ctx).by_status(status)
    ]


@router.get("/{quote_id}", response_model=QuoteView)
async def quote(quote_id: UUID, session: Session, ctx: Context, config: Config) -> QuoteView:
    return await QuoteService(session, ctx, config).view(quote_id)


@router.get("/{quote_id}/pdf")
async def pdf(quote_id: UUID, session: Session, ctx: Context, config: Config) -> Response:
    return Response(
        await QuoteService(session, ctx, config).pdf(quote_id),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="quotation.pdf"',
            "Cache-Control": "no-store",
        },
    )
