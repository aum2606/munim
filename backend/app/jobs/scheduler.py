"""Periodic work. Runs in the worker loop and only enqueues per-tenant jobs; the jobs themselves go
through the tenant-scoped repositories."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select

from app.core.config import Settings
from app.core.context import TenantContext
from app.db.models import FollowUp, Quote, QuoteStatus
from app.db.session import SessionMaker
from app.jobs.queue import enqueue


async def enqueue_due_follow_ups(sessionmaker: SessionMaker, settings: Settings) -> int:
    """One `create_follow_ups` job for every business with a sent quote nobody has nudged yet."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.followup_after_days)
    async with sessionmaker() as session:
        tenants = await session.scalars(
            select(Quote.tenant_id)
            .where(
                Quote.status == QuoteStatus.SENT,
                Quote.sent_at <= cutoff,
                ~exists().where(FollowUp.quote_id == Quote.id),
            )
            .distinct()
        )
        count = 0
        for tenant_id in tenants:
            await enqueue(session, TenantContext.system(tenant_id), "create_follow_ups")
            count += 1
        await session.commit()
    return count
