"""Operator tool for a forgotten password when email reset is not set up.

    docker compose -f docker-compose.prod.yml exec api python -m app.services.set_password EMAIL

It asks for the new password on the terminal (never on the command line, so it stays out of shell
history), and signs that user out everywhere.
"""

import asyncio
import getpass
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.security import hash_password
from app.db.session import make_engine, make_sessionmaker
from app.repositories.auth import AuthRepository

_MIN, _MAX = 10, 128  # the same rules as the sign-up form


async def set_password(session: AsyncSession, email: str, new_password: str) -> None:
    if not _MIN <= len(new_password) <= _MAX:
        raise ValueError(f"The password must be {_MIN} to {_MAX} characters")
    repo = AuthRepository(session)
    user = await repo.get_user_by_email(email.strip().lower())
    if user is None:
        raise NotFoundError("No account with that email")
    user.password_hash = hash_password(new_password)
    user.failed_login_count, user.locked_until = 0, None
    await repo.revoke_all_refresh_tokens(user.id)


async def main(email: str) -> None:
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Again: "):
        raise SystemExit("The two passwords differ")
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            await set_password(session, email, password)
            await session.commit()
    finally:
        await engine.dispose()
    print("Password changed.")  # noqa: T201


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.services.set_password EMAIL")
    asyncio.run(main(sys.argv[1]))
