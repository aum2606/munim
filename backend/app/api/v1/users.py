import uuid

from fastapi import APIRouter, status

from app.core.deps import CtxDep, OwnerDep, SessionDep
from app.core.errors import NotFoundError
from app.repositories.users import UserRepository
from app.schemas.auth import MeResponse, TenantOut, UserCreate, UserOut, UserUpdate
from app.services.users import UserService

router = APIRouter(tags=["users"])


@router.get("/me", response_model=MeResponse)
async def me(ctx: CtxDep, session: SessionDep) -> MeResponse:
    repo = UserRepository(session, ctx)
    user = await repo.get(ctx.user_id) if ctx.user_id else None
    tenant = await repo.get_own_tenant()
    if user is None or tenant is None:
        raise NotFoundError("Account not found")
    return MeResponse(user=UserOut.model_validate(user), tenant=TenantOut.model_validate(tenant))


@router.get("/users", response_model=list[UserOut])
async def list_users(ctx: OwnerDep, session: SessionDep) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in await UserRepository(session, ctx).list()]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, ctx: OwnerDep, session: SessionDep) -> UserOut:
    return UserOut.model_validate(await UserService(session, ctx).create(body))


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, ctx: OwnerDep, session: SessionDep
) -> UserOut:
    return UserOut.model_validate(await UserService(session, ctx).update(user_id, body))
