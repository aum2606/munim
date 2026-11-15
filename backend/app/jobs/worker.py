import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog

from app.core.config import get_settings
from app.core.context import TenantContext
from app.core.logging import configure_logging
from app.db.session import SessionMaker, make_engine, make_sessionmaker
from app.jobs.queue import ClaimedJob, claim_batch, mark_done, mark_failed

log = structlog.get_logger()

Handler = Callable[[SessionMaker, TenantContext, dict[str, Any]], Awaitable[None]]


async def process_batch(
    sessionmaker: SessionMaker,
    handlers: dict[str, Handler],
    *,
    limit: int = 10,
    lease_s: int = 120,
) -> int:
    """Claim and run one batch of due jobs. Returns how many were claimed."""
    async with sessionmaker() as session:
        jobs = await claim_batch(session, limit=limit, lease_s=lease_s)
        await session.commit()  # the lease is durable before any handler runs
    for job in jobs:
        await _run(sessionmaker, handlers, job, lease_s)
    return len(jobs)


async def _run(
    sessionmaker: SessionMaker, handlers: dict[str, Handler], job: ClaimedJob, lease_s: int
) -> None:
    handler = handlers.get(job.kind)
    retry = handler is not None  # an unknown kind can never succeed on retry
    try:
        if handler is None:
            raise LookupError(f"no handler for job kind {job.kind!r}")
        # Time-box to the lease so a hung handler cannot outlive its claim and run twice.
        await asyncio.wait_for(
            handler(sessionmaker, TenantContext.system(job.tenant_id), job.payload), lease_s
        )
    except Exception as exc:
        # Class name only: exception text can contain customer messages.
        log.warning("job_failed", job_id=str(job.id), kind=job.kind, error=type(exc).__name__)
        async with sessionmaker() as session:
            await mark_failed(session, job.id, f"{type(exc).__name__}", retry=retry)
            await session.commit()
    else:
        async with sessionmaker() as session:
            await mark_done(session, job.id)
            await session.commit()


async def run_worker(
    sessionmaker: SessionMaker,
    handlers: dict[str, Handler],
    stop: asyncio.Event,
    *,
    poll_s: float = 1.0,
    lease_s: int = 120,
) -> None:
    while not stop.is_set():
        try:
            claimed = await process_batch(sessionmaker, handlers, lease_s=lease_s)
        except Exception:
            log.error("worker_batch_failed", exc_info=True)  # e.g. DB restarting: keep polling
            claimed = 0
        if claimed == 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), poll_s)


async def main() -> None:
    from app.jobs.handlers import build_handlers  # late: handlers import this module's Handler
    from app.llm.embedder import LocalEmbedder
    from app.llm.openai_compat import ChainLLMClient

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    embedder = LocalEmbedder(settings.embedding_model, settings.embedding_cache_dir)
    http = httpx.AsyncClient()
    llm = ChainLLMClient.from_settings(settings, http)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)  # finish the current batch, then exit
    log.info("worker_started")
    try:
        await run_worker(
            make_sessionmaker(engine),
            build_handlers(embedder, settings, llm),
            stop,
            poll_s=settings.job_poll_seconds,
            lease_s=settings.job_lease_seconds,
        )
    finally:
        await http.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
