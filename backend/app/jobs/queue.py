"""Postgres-backed job queue (no Redis). Claiming uses FOR UPDATE SKIP LOCKED, so any number of
workers can poll the same table and each job is handed to exactly one of them at a time.

`enqueue` is tenant-scoped like every other repository. The claim/complete/fail functions are
system-level on purpose: the worker serves all tenants and hands each handler a TenantContext.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import Job, JobStatus

_MAX_ERROR_CHARS = 500


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    tenant_id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


async def enqueue(
    session: AsyncSession,
    ctx: TenantContext,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    run_at: datetime | None = None,
    max_attempts: int = 5,
) -> uuid.UUID:
    job = Job(
        tenant_id=ctx.tenant_id,
        kind=kind,
        payload=payload or {},
        run_at=run_at or datetime.now(UTC),
        max_attempts=max_attempts,
        status=JobStatus.QUEUED,
    )
    session.add(job)
    await session.flush()
    return job.id


async def claim_batch(session: AsyncSession, *, limit: int, lease_s: int) -> list[ClaimedJob]:
    """Take up to `limit` due jobs and lease them. A job whose worker died (lease expired) is
    picked up again, until it runs out of attempts."""
    now = datetime.now(UTC)
    due = or_(
        and_(Job.status == JobStatus.QUEUED, Job.run_at <= now),
        and_(Job.status == JobStatus.RUNNING, Job.locked_until < now),
    )
    rows = await session.scalars(
        select(Job).where(due).order_by(Job.run_at).limit(limit).with_for_update(skip_locked=True)
    )
    claimed: list[ClaimedJob] = []
    for job in rows:
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.DEAD
            job.last_error = "lease expired after the final attempt"
            continue
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_until = now + timedelta(seconds=lease_s)
        claimed.append(
            ClaimedJob(job.id, job.tenant_id, job.kind, job.payload, job.attempts, job.max_attempts)
        )
    return claimed


async def mark_done(session: AsyncSession, job_id: uuid.UUID) -> None:
    job = await session.get(Job, job_id)
    if job is not None:
        job.status = JobStatus.DONE
        job.locked_until = None


async def mark_failed(
    session: AsyncSession, job_id: uuid.UUID, error: str, *, retry: bool = True
) -> None:
    """Retry with exponential backoff (5s, 10s, 20s, ... capped at 10 min), then go dead."""
    job = await session.get(Job, job_id)
    if job is None:
        return
    job.last_error = error[:_MAX_ERROR_CHARS]
    job.locked_until = None
    if retry and job.attempts < job.max_attempts:
        job.status = JobStatus.QUEUED
        job.run_at = datetime.now(UTC) + timedelta(seconds=min(5 * 2 ** (job.attempts - 1), 600))
    else:
        job.status = JobStatus.DEAD
