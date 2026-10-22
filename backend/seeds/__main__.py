import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.security import hash_password
from app.llm.factory import make_embedder
from seeds.demo import demo_businesses, seed_demo


async def main() -> None:
    settings = Settings()
    password = settings.demo_seed_password.get_secret_value()
    if len(password) < 12:
        raise SystemExit(
            "Set DEMO_SEED_PASSWORD to at least 12 characters before running make seed"
        )
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        await seed_demo(
            async_sessionmaker(engine, expire_on_commit=False),
            make_embedder(settings),
            await run_in_threadpool(hash_password, password),
        )
    finally:
        await engine.dispose()
    print("Seeded electronics, photography and printing demo workspaces.")
    print("Demo owners: " + ", ".join(business.email for business in demo_businesses()))
    print("Password comes from DEMO_SEED_PASSWORD; existing demo owner passwords are preserved.")


if __name__ == "__main__":
    asyncio.run(main())
