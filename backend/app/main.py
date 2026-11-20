import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import health, webhooks
from app.api.v1 import router as v1_router
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging
from app.core.ratelimit import SlidingWindowLimiter
from app.core.security import prompt_canary
from app.db.session import make_engine, make_sessionmaker
from app.llm.openai_compat import ChainLLMClient
from app.llm.prompting import set_canary

log = structlog.get_logger()

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",  # API responses carry account data and tokens
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    set_canary(prompt_canary(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        http = httpx.AsyncClient()
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.llm = ChainLLMClient.from_settings(settings, http)
        yield
        await http.aclose()
        await engine.dispose()

    prod = settings.app_env == "prod"
    app = FastAPI(
        title="Munim",
        lifespan=lifespan,
        docs_url=None if prod else "/docs",  # no API explorer in production
        redoc_url=None,
        openapi_url=None if prod else "/openapi.json",
    )
    app.state.settings = settings
    app.state.limiter = SlidingWindowLimiter()

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,  # explicit list: never "*" with credentials
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    _add_request_middleware(app)
    _add_error_handlers(app)

    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(v1_router, prefix="/api/v1")
    return app


def _add_request_middleware(app: FastAPI) -> None:
    """Request id, security headers and one access log line per request."""

    @app.middleware("http")
    async def request_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        structlog.contextvars.clear_contextvars()
        request_id = uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers.update(_SECURITY_HEADERS)
        response.headers["X-Request-ID"] = request_id
        # Method, path and status only: never bodies, headers or query strings.
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.perf_counter() - started) * 1000),
        )
        return response


def _add_error_handlers(app: FastAPI) -> None:
    """Domain errors map to their HTTP status; nothing else leaks internals."""

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        retry_after = getattr(exc, "retry_after", None)
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status_code,
            headers={"Retry-After": str(retry_after)} if retry_after else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default echoes the submitted value ("input"), which could be a password.
        fields = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            {"error": {"code": "validation_error", "message": "Invalid request", "fields": fields}},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", error_type=type(exc).__name__, exc_info=True)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "Something went wrong"}},
            status_code=500,
        )
