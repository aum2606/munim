from uuid import UUID

from fastapi import APIRouter, Response

from app.core.auth import AuthService
from app.core.deps import Config, Context, Owner, Session
from app.core.errors import Unauthorized
from app.repositories.identity import UserRepository
from app.schemas.auth import LoginInput, RefreshInput, RegisterInput, RenameInput, Tokens, UserView

router = APIRouter()


@router.post("/auth/register", response_model=Tokens, status_code=201)
async def register(request: RegisterInput, session: Session, settings: Config) -> Tokens:
    return await AuthService(session, settings).register(request)


@router.post("/auth/login", response_model=Tokens)
async def login(request: LoginInput, session: Session, settings: Config) -> Tokens:
    return await AuthService(session, settings).login(request)


@router.post("/auth/refresh", response_model=Tokens)
async def refresh(request: RefreshInput, session: Session, settings: Config) -> Tokens:
    return await AuthService(session, settings).refresh(request.refresh_token)


@router.post("/auth/logout", status_code=204)
async def logout(request: RefreshInput, session: Session, settings: Config) -> Response:
    await AuthService(session, settings).logout(request.refresh_token)
    return Response(status_code=204)


@router.get("/me", response_model=UserView)
async def me(ctx: Context, session: Session) -> UserView:
    if ctx.user_id is None:
        raise Unauthorized()
    return UserView.model_validate(await UserRepository(session, ctx).get(ctx.user_id))


@router.get("/users", response_model=list[UserView])
async def users(ctx: Owner, session: Session) -> list[UserView]:
    return [UserView.model_validate(user) for user in await UserRepository(session, ctx).list()]


@router.get("/users/{user_id}", response_model=UserView)
async def get_user(user_id: UUID, ctx: Owner, session: Session) -> UserView:
    return UserView.model_validate(await UserRepository(session, ctx).get(user_id))


@router.patch("/users/{user_id}", response_model=UserView)
async def rename_user(
    user_id: UUID, request: RenameInput, ctx: Owner, session: Session
) -> UserView:
    user = await UserRepository(session, ctx).rename(user_id, request.name)
    await session.commit()
    return UserView.model_validate(user)
