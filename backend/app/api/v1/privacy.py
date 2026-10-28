from uuid import UUID

from fastapi import APIRouter, Query

from app.core.deps import Config, Owner, Session
from app.core.privacy import PrivacyService
from app.schemas.privacy import EraseCustomer, ErasureView

router = APIRouter()


@router.get("/customers")
async def customers(
    session: Session, ctx: Owner, config: Config, q: str = Query(default="", max_length=200)
) -> list[dict[str, str | None]]:
    return [
        {
            "id": str(customer.id),
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email,
        }
        for customer in await PrivacyService(session, ctx, config).repository.customers(q)
    ]


@router.delete("/customers/{customer_id}", response_model=ErasureView)
async def erase_customer(
    customer_id: UUID, body: EraseCustomer, session: Session, ctx: Owner, config: Config
) -> ErasureView:
    return await PrivacyService(session, ctx, config).erase(customer_id, body)


@router.post("/privacy/erasures/{erasure_id}/retry", response_model=ErasureView)
async def retry_erasure(
    erasure_id: UUID, session: Session, ctx: Owner, config: Config
) -> ErasureView:
    return await PrivacyService(session, ctx, config).finish_files(erasure_id)
