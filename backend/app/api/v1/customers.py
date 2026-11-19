import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import OwnerDep, SessionDep, SettingsDep
from app.db.models import Customer
from app.repositories.customers import CustomerRepository
from app.schemas.customers import CustomerExport, CustomerOut
from app.services.customers import CustomerService

router = APIRouter(tags=["customers"])


@router.get("/customers", response_model=list[CustomerOut])
async def list_customers(
    ctx: OwnerDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=60)] = None,
) -> list[Customer]:
    """Find a customer by phone number or name, to export or erase their data."""
    return await CustomerRepository(session, ctx).browse(q)


@router.get("/customers/{customer_id}/export", response_model=CustomerExport)
async def export_customer(
    customer_id: uuid.UUID, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> CustomerExport:
    return await CustomerService(session, ctx, settings).export(customer_id)


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def erase_customer(
    customer_id: uuid.UUID, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> None:
    """Permanently delete a customer and everything they said. It cannot be undone."""
    await CustomerService(session, ctx, settings).erase(customer_id)
