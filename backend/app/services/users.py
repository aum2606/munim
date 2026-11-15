import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.db.models import User
from app.repositories.auth import AuthRepository
from app.repositories.users import UserRepository
from app.schemas.auth import UserCreate, UserUpdate


class UserService:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._ctx = ctx
        self._users = UserRepository(session, ctx)
        self._auth = AuthRepository(session)

    async def create(self, data: UserCreate) -> User:
        if await self._auth.get_user_by_email(data.email):
            raise ConflictError("An account with this email already exists")
        try:
            return await self._users.add(
                email=data.email,
                name=data.name,
                password_hash=hash_password(data.password),
                role=data.role,
            )
        except IntegrityError as exc:
            raise ConflictError("An account with this email already exists") from exc

    async def update(self, user_id: uuid.UUID, data: UserUpdate) -> User:
        user = await self._users.get(user_id)
        if user is None:  # also what a user of another tenant looks like: no existence leak
            raise NotFoundError("User not found")
        if data.is_active is not None and user.id == self._ctx.user_id:
            raise ForbiddenError("You cannot change your own active status")
        if data.name is not None:
            user.name = data.name
        if data.is_active is not None:
            user.is_active = data.is_active
            if not data.is_active:
                await self._auth.revoke_all_refresh_tokens(user.id)
        return user
