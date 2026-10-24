import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.auth import router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.documents import router as documents_router
from app.api.v1.leads import router as leads_router
from app.api.v1.pricing_rules import router as pricing_rules_router
from app.api.v1.quotes import router as quotes_router
from app.api.v1.requirements import router as requirements_router
from app.api.v1.tenant import router as tenant_router
from app.api.v1.widget import router as widget_router
from app.api.v1.workspace import router as workspace_router
from app.channels.web import WidgetCORSMiddleware
from app.core.config import Settings
from app.core.deps import Session
from app.core.errors import DomainError
from app.core.logging import configure_logging
from app.repositories.health import check_database
from app.workers.queue import ArqJobQueue


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    configure_logging()
    engine = create_async_engine(config.database_url, pool_pre_ping=True, hide_parameters=True)
    redis = Redis.from_url(config.redis_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await redis.aclose()
        await engine.dispose()

    app = FastAPI(title="Munim", lifespan=lifespan)
    app.state.redis = redis
    app.state.settings = config
    app.state.jobs = ArqJobQueue(config.redis_url, config.debounce_seconds)
    app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins.split(","),
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.add_middleware(WidgetCORSMiddleware)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
        return JSONResponse(
            {"detail": error.message}, status_code=error.status_code, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        # Never echo invalid input: it may contain passwords or customer PII.
        errors = [
            {"loc": list(e["loc"]), "type": e["type"], "msg": e["msg"]} for e in error.errors()
        ]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(session: Session) -> JSONResponse:
        try:
            async with asyncio.timeout(3):
                await check_database(session)
                await redis.ping()
        except (SQLAlchemyError, RedisError, OSError, TimeoutError) as error:
            structlog.get_logger().warning("readiness_failed", error=type(error).__name__)
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    app.include_router(leads_router, prefix="/api/v1")
    app.include_router(quotes_router, prefix="/api/v1")
    app.include_router(pricing_rules_router, prefix="/api/v1")
    app.include_router(requirements_router, prefix="/api/v1")
    app.include_router(router, prefix="/api/v1")
    app.include_router(catalog_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(widget_router, prefix="/api/v1")
    app.include_router(tenant_router, prefix="/api/v1")
    app.include_router(workspace_router, prefix="/api/v1")
    return app
