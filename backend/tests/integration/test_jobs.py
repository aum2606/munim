import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select, update

from app.core.context import TenantContext
from app.db.models import Job, JobStatus
from app.db.session import SessionMaker
from app.jobs.queue import claim_batch, enqueue
from app.jobs.worker import Handler, process_batch
from tests.conftest import make_tenant


@pytest.fixture
async def ctx(sessionmaker: SessionMaker) -> TenantContext:
    async with sessionmaker() as session:  # the queue is shared: start from empty
        await session.execute(delete(Job))
        await session.commit()
    return await make_tenant(sessionmaker)


async def _enqueue(sessionmaker: SessionMaker, ctx: TenantContext, n: int = 1, **kw: Any) -> None:
    async with sessionmaker() as session:
        for i in range(n):
            await enqueue(session, ctx, "count", {"n": i}, **kw)
        await session.commit()


async def _jobs(sessionmaker: SessionMaker) -> list[Job]:
    async with sessionmaker() as session:
        return list(await session.scalars(select(Job).order_by(Job.created_at)))


async def _noop(_: SessionMaker, __: TenantContext, ___: dict[str, Any]) -> None:
    return None


async def test_two_competing_workers_run_each_job_exactly_once(
    sessionmaker: SessionMaker, ctx: TenantContext
) -> None:
    seen: list[int] = []

    async def handler(_: SessionMaker, __: TenantContext, payload: dict[str, Any]) -> None:
        await asyncio.sleep(0.005)
        seen.append(payload["n"])

    await _enqueue(sessionmaker, ctx, n=40)

    async def worker() -> None:
        while await process_batch(sessionmaker, {"count": handler}, limit=3):
            pass

    await asyncio.gather(worker(), worker())
    assert sorted(seen) == list(range(40))
    assert {j.status for j in await _jobs(sessionmaker)} == {JobStatus.DONE}


async def test_handler_receives_the_jobs_own_tenant(
    sessionmaker: SessionMaker, ctx: TenantContext
) -> None:
    other = await make_tenant(sessionmaker)
    got: list[TenantContext] = []

    async def handler(_: SessionMaker, tenant: TenantContext, __: dict[str, Any]) -> None:
        got.append(tenant)

    await _enqueue(sessionmaker, ctx)
    await _enqueue(sessionmaker, other)
    await process_batch(sessionmaker, {"count": handler})
    assert sorted(str(t.tenant_id) for t in got) == sorted(
        [str(ctx.tenant_id), str(other.tenant_id)]
    )
    assert all(t.user_id is None for t in got)  # system actor, not a person


async def test_future_jobs_wait_until_due(sessionmaker: SessionMaker, ctx: TenantContext) -> None:
    await _enqueue(sessionmaker, ctx, run_at=datetime.now(UTC) + timedelta(hours=1))
    assert await process_batch(sessionmaker, {"count": _noop}) == 0


async def test_failures_retry_with_backoff_then_go_dead(
    sessionmaker: SessionMaker, ctx: TenantContext
) -> None:
    async def boom(_: SessionMaker, __: TenantContext, ___: dict[str, Any]) -> None:
        raise ValueError("contains customer text 9876543210")

    handlers: dict[str, Handler] = {"count": boom}
    await _enqueue(sessionmaker, ctx, max_attempts=2)

    assert await process_batch(sessionmaker, handlers) == 1
    (job,) = await _jobs(sessionmaker)
    assert job.status == JobStatus.QUEUED and job.attempts == 1
    assert job.run_at > datetime.now(UTC)  # backed off
    assert job.last_error == "ValueError"  # class only, never the message

    async with sessionmaker() as session:  # skip the wait
        await session.execute(update(Job).values(run_at=datetime.now(UTC)))
        await session.commit()
    assert await process_batch(sessionmaker, handlers) == 1
    (job,) = await _jobs(sessionmaker)
    assert job.status == JobStatus.DEAD and job.attempts == 2


async def test_unknown_kind_goes_dead_without_retrying(
    sessionmaker: SessionMaker, ctx: TenantContext
) -> None:
    await _enqueue(sessionmaker, ctx)
    await process_batch(sessionmaker, {})
    (job,) = await _jobs(sessionmaker)
    assert job.status == JobStatus.DEAD and job.attempts == 1


async def test_job_of_a_crashed_worker_is_picked_up_again(
    sessionmaker: SessionMaker, ctx: TenantContext
) -> None:
    await _enqueue(sessionmaker, ctx, max_attempts=2)
    async with sessionmaker() as session:  # a worker claims it with an already-expired lease...
        assert len(await claim_batch(session, limit=5, lease_s=-1)) == 1
        await session.commit()
    async with sessionmaker() as session:  # ...and "dies"; the next claim recovers it
        recovered = await claim_batch(session, limit=5, lease_s=60)
        await session.commit()
    assert [j.attempts for j in recovered] == [2]

    async with sessionmaker() as session:  # out of attempts: dead, not run forever
        await session.execute(update(Job).values(locked_until=datetime.now(UTC) - timedelta(1)))
        await session.commit()
    async with sessionmaker() as session:
        assert await claim_batch(session, limit=5, lease_s=60) == []
        await session.commit()
    assert (await _jobs(sessionmaker))[0].status == JobStatus.DEAD
