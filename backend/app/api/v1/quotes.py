import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.core.deps import CtxDep, OwnerDep, SessionDep, SettingsDep
from app.db.models import QuoteStatus
from app.repositories.quotes import QuoteRepository
from app.schemas.quote import (
    QuoteDetail,
    QuoteItemOut,
    QuoteSummary,
    QuoteUpdate,
    TaxGroupOut,
)
from app.services.quotes import LineEdit, QuoteService, QuoteView

router = APIRouter(prefix="/quotes", tags=["quotes"])


async def _detail(session: SessionDep, ctx: CtxDep, view: QuoteView) -> QuoteDetail:
    q = view.quote
    return QuoteDetail(
        id=q.id,
        quote_number=q.quote_number,
        status=q.status,
        customer_name=await QuoteRepository(session, ctx).customer_name(q.lead_id),
        valid_until=q.valid_until,
        buyer_state_code=q.buyer_state_code,
        subtotal_paise=q.subtotal_paise,
        discount_paise=q.discount_paise,
        cgst_paise=q.cgst_paise,
        sgst_paise=q.sgst_paise,
        igst_paise=q.igst_paise,
        round_off_paise=q.round_off_paise,
        total_paise=q.total_paise,
        items=[QuoteItemOut.model_validate(i) for i in view.items],
        tax_groups=[TaxGroupOut(**vars(g)) for g in view.totals.groups],
        sent_at=q.sent_at,
        created_at=q.created_at,
    )


@router.get("", response_model=list[QuoteSummary])
async def list_quotes(
    ctx: CtxDep,
    session: SessionDep,
    status: Annotated[QuoteStatus | None, Query()] = None,
) -> list[QuoteSummary]:
    rows = await QuoteRepository(session, ctx).summaries(status)
    return [
        QuoteSummary(
            id=q.id,
            quote_number=q.quote_number,
            status=q.status,
            total_paise=q.total_paise,
            valid_until=q.valid_until,
            customer_name=name,
            unpriced_lines=unpriced,
            created_at=q.created_at,
        )
        for q, name, unpriced in rows
    ]


@router.get("/{quote_id}", response_model=QuoteDetail)
async def get_quote(
    quote_id: uuid.UUID, ctx: CtxDep, session: SessionDep, settings: SettingsDep
) -> QuoteDetail:
    return await _detail(session, ctx, await QuoteService(session, ctx, settings).view(quote_id))


@router.patch("/{quote_id}", response_model=QuoteDetail)
async def edit_quote(
    quote_id: uuid.UUID,
    body: QuoteUpdate,
    ctx: OwnerDep,
    session: SessionDep,
    settings: SettingsDep,
) -> QuoteDetail:
    view = await QuoteService(session, ctx, settings).update(
        quote_id,
        [LineEdit(e.id, e.qty, e.unit_price_paise, e.discount_paise) for e in body.items],
        body.buyer_state_code,
        set_buyer_state="buyer_state_code" in body.model_fields_set,
    )
    return await _detail(session, ctx, view)


@router.post("/{quote_id}/approve", response_model=QuoteDetail)
async def approve_quote(
    quote_id: uuid.UUID, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> QuoteDetail:
    return await _detail(session, ctx, await QuoteService(session, ctx, settings).approve(quote_id))


@router.post("/{quote_id}/reject", response_model=QuoteDetail)
async def reject_quote(
    quote_id: uuid.UUID, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> QuoteDetail:
    return await _detail(session, ctx, await QuoteService(session, ctx, settings).reject(quote_id))


@router.post("/{quote_id}/mark-accepted", response_model=QuoteDetail)
async def accept_quote(
    quote_id: uuid.UUID, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> QuoteDetail:
    view = await QuoteService(session, ctx, settings).mark_accepted(quote_id)
    return await _detail(session, ctx, view)


@router.get("/{quote_id}/pdf")
async def quote_pdf(
    quote_id: uuid.UUID, ctx: CtxDep, session: SessionDep, settings: SettingsDep
) -> Response:
    service = QuoteService(session, ctx, settings)
    view = await service.view(quote_id)
    filename = view.quote.quote_number.replace(
        "/", "-"
    )  # the number is ours, but never trust a path
    return Response(
        await service.pdf(quote_id),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}.pdf"'},
    )
