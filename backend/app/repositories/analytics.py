from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext
from app.db.models.analytics import WeeklyDigest
from app.repositories.scoped import ScopedRepository
from app.schemas.insights import AnalyticsResult, AnalyticsTool, Cell, InsightPlan, Period

IST = ZoneInfo("Asia/Kolkata")


def period_bounds(period: Period, now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(IST)
    if period == Period.THIS_WEEK:
        start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=local.weekday()
        )
    elif period == Period.THIS_MONTH:
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = local - timedelta(
            days={Period.WEEK: 7, Period.MONTH: 30, Period.QUARTER: 90}[period]
        )
    return start.astimezone(UTC), now.astimezone(UTC)


# These are the complete SQL allow-list. Never interpolate model/user strings into SQL.
QUERIES = {
    AnalyticsTool.AWAITING: """
        SELECT l.id AS lead_id, c.name AS customer, l.conversation_id,
               v.last_customer_msg_at AS last_customer_message, count(*) OVER() AS matched_total
        FROM leads l JOIN conversations v ON v.id=l.conversation_id AND v.tenant_id=:tenant
        JOIN customers c ON c.id=l.customer_id AND c.tenant_id=:tenant
        WHERE l.tenant_id=:tenant AND l.stage NOT IN ('won','lost') AND v.status='open'
          AND v.last_customer_msg_at >= :start AND v.last_customer_msg_at < :end
          AND (v.last_business_msg_at IS NULL OR v.last_customer_msg_at > v.last_business_msg_at)
        ORDER BY v.last_customer_msg_at, l.id LIMIT :limit
    """,
    AnalyticsTool.SILENT: """
        SELECT l.id AS lead_id, c.name AS customer, l.conversation_id,
               v.last_business_msg_at AS last_business_message, count(*) OVER() AS matched_total
        FROM leads l JOIN conversations v ON v.id=l.conversation_id AND v.tenant_id=:tenant
        JOIN customers c ON c.id=l.customer_id AND c.tenant_id=:tenant
        WHERE l.tenant_id=:tenant AND l.stage NOT IN ('won','lost') AND v.status='open'
          AND v.last_business_msg_at >= :start AND v.last_business_msg_at < :end
          AND v.last_business_msg_at <= :cutoff
          AND (v.last_customer_msg_at IS NULL OR v.last_customer_msg_at < v.last_business_msg_at)
        ORDER BY v.last_business_msg_at, l.id LIMIT :limit
    """,
    AnalyticsTool.NOT_FOLLOWED: """
        SELECT l.id AS lead_id, c.name AS customer, l.conversation_id,
               l.created_at AS lead_created, count(*) OVER() AS matched_total
        FROM leads l JOIN customers c ON c.id=l.customer_id AND c.tenant_id=:tenant
        JOIN conversations v ON v.id=l.conversation_id AND v.tenant_id=:tenant
        WHERE l.tenant_id=:tenant AND l.stage NOT IN ('won','lost') AND v.status='open'
          AND l.created_at < :cutoff
          AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.tenant_id=:tenant
              AND m.conversation_id=l.conversation_id AND m.direction='out'
              AND m.external_id LIKE 'followup:%' AND m.created_at >= :cutoff AND m.created_at <
            :end)
        ORDER BY l.created_at, l.id LIMIT :limit
    """,
    AnalyticsTool.TOP: """
        SELECT c.id AS catalog_item_id, c.name AS item, count(DISTINCT e.source_key)::bigint AS
            enquiries,
               count(*) OVER() AS matched_total
        FROM analytics_events e JOIN catalog_items c
          ON c.id::text=e.properties->>'catalog_item_id' AND c.tenant_id=:tenant
        WHERE e.tenant_id=:tenant AND e.event='catalog_enquiry'
          AND e.occurred_at >= :start AND e.occurred_at < :end
        GROUP BY c.id,c.name ORDER BY enquiries DESC,c.name,c.id LIMIT :limit
    """,
    AnalyticsTool.TREND: """
        WITH first_in AS (SELECT conversation_id,min(created_at) AS first_at FROM messages
            WHERE tenant_id=:tenant AND direction='in' GROUP BY conversation_id),
        buckets AS (SELECT date_trunc(:granularity, d)::date AS day
            FROM generate_series(timezone('Asia/Kolkata',CAST(:start AS timestamptz))::date,
                timezone('Asia/Kolkata',CAST(:end AS timestamptz)-interval '1 microsecond')::date,
                interval '1 day') d GROUP BY 1)
        SELECT b.day AS date,count(f.conversation_id)::bigint AS enquiries FROM buckets b
        LEFT JOIN first_in f ON date_trunc(:granularity,
            timezone('Asia/Kolkata',f.first_at))::date=b.day
            AND f.first_at>=:start AND f.first_at<:end
        GROUP BY b.day ORDER BY b.day
    """,
    AnalyticsTool.INTENT: """
        SELECT coalesce(intent,'unclassified') AS intent,count(*)::bigint AS messages FROM
            messages
        WHERE tenant_id=:tenant AND direction='in' AND created_at>=:start AND created_at<:end
        GROUP BY intent ORDER BY messages DESC, intent
    """,
    AnalyticsTool.FUNNEL: """
        SELECT status,count(*)::bigint AS quotes FROM quotes
        WHERE tenant_id=:tenant AND created_at>=:start AND created_at<:end
        GROUP BY status ORDER BY status
    """,
    AnalyticsTool.QUOTES: """
        SELECT id AS quote_id,quote_number,status,count(*) OVER() AS matched_total FROM quotes
        WHERE tenant_id=:tenant AND status=:status AND created_at>=:start AND created_at<:end
        ORDER BY created_at DESC,id LIMIT :limit
    """,
    AnalyticsTool.RESPONSE: """
        WITH first_in AS (SELECT conversation_id,min(created_at) AS first_at FROM messages
            WHERE tenant_id=:tenant AND direction='in' GROUP BY conversation_id),
        replies AS (SELECT f.conversation_id,extract(epoch FROM min(m.created_at)-f.first_at) AS
            seconds
            FROM first_in f JOIN messages m ON m.tenant_id=:tenant
                AND m.conversation_id=f.conversation_id AND m.direction='out' AND
            m.created_at>=f.first_at
            WHERE f.first_at>=:start AND f.first_at<:end GROUP BY f.conversation_id,f.first_at)
        SELECT count(*)::bigint AS replied_conversations,round(avg(seconds))::bigint AS
            average_seconds,
            round(CAST(percentile_cont(0.5) WITHIN GROUP(ORDER BY seconds) AS numeric))::bigint
            AS median_seconds
        FROM replies
    """,
    AnalyticsTool.GAPS: """
        SELECT id AS gap_id,question,occurrences,status,count(*) OVER() AS matched_total
        FROM knowledge_gaps WHERE tenant_id=:tenant AND (NOT :open_only OR status='open')
        ORDER BY occurrences DESC,id LIMIT :limit
    """,
    AnalyticsTool.CHANNEL: """
        WITH first_in AS (SELECT conversation_id,min(created_at) AS first_at FROM messages
            WHERE tenant_id=:tenant AND direction='in' GROUP BY conversation_id)
        SELECT v.channel,count(*)::bigint AS enquiries FROM first_in f JOIN conversations v
            ON v.id=f.conversation_id AND v.tenant_id=:tenant
        WHERE f.first_at>=:start AND f.first_at<:end GROUP BY v.channel ORDER BY enquiries
            DESC,v.channel
    """,
    AnalyticsTool.LOST: """
        SELECT coalesce(nullif(lost_reason,''),'Unspecified') AS reason,count(*)::bigint AS leads
        FROM leads WHERE tenant_id=:tenant AND stage='lost' AND updated_at>=:start AND
            updated_at<:end
        GROUP BY lost_reason ORDER BY leads DESC,reason
    """,
}


def cell(value: Any) -> Cell:
    if value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, Decimal):
        return int(value)
    return str(value)


class AnalyticsRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self.session, self.ctx = session, ctx

    async def query(
        self,
        plan: InsightPlan,
        start: datetime,
        end: datetime,
    ) -> AnalyticsResult:
        assert plan.tool is not None
        result = await self.session.execute(
            text(QUERIES[plan.tool]),
            {
                "tenant": self.ctx.tenant_id,
                "start": start,
                "end": end,
                "cutoff": end - timedelta(days=plan.days),
                "limit": plan.limit,
                "status": plan.status,
                "open_only": plan.open_only,
                "granularity": plan.granularity,
            },
        )
        columns = [key for key in result.keys() if key != "matched_total"]
        raw = list(result.mappings())
        total = int(raw[0]["matched_total"]) if raw and "matched_total" in raw[0] else len(raw)
        rows = [{key: cell(row[key]) for key in columns} for row in raw]
        return AnalyticsResult(columns=columns, rows=rows, total=total, truncated=total > len(rows))

    async def metrics(self, start: datetime, end: datetime) -> dict[str, int]:
        result = (
            (
                await self.session.execute(
                    text("""
            WITH cohort AS (SELECT v.* FROM conversations v WHERE v.tenant_id=:tenant
                AND EXISTS (SELECT 1 FROM messages m WHERE m.tenant_id=:tenant
                    AND m.conversation_id=v.id AND m.direction='in')
                AND (SELECT min(m.created_at) FROM messages m WHERE m.tenant_id=:tenant
                    AND m.conversation_id=v.id AND m.direction='in')>=:start
                AND (SELECT min(m.created_at) FROM messages m WHERE m.tenant_id=:tenant
                    AND m.conversation_id=v.id AND m.direction='in')<:end)
            SELECT count(*)::bigint AS enquiries,
                count(*) FILTER(WHERE status='closed')::bigint AS closed,
                count(*) FILTER(WHERE status='closed' AND NOT EXISTS
                    (SELECT 1 FROM handoffs h WHERE h.tenant_id=:tenant AND
            h.conversation_id=cohort.id))::bigint AS ai_resolved,
                (SELECT count(*) FROM messages WHERE tenant_id=:tenant AND direction='in'
                    AND created_at>=:start AND created_at<:end)::bigint AS inbound,
                (SELECT count(*) FROM knowledge_gaps WHERE tenant_id=:tenant AND
            status='open')::bigint AS gaps
            FROM cohort
        """),
                    {"tenant": self.ctx.tenant_id, "start": start, "end": end},
                )
            )
            .mappings()
            .one()
        )
        return {key: int(value) for key, value in result.items()}


class DigestRepository(ScopedRepository[WeeklyDigest]):
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        super().__init__(session, ctx, WeeklyDigest)

    async def latest(self) -> WeeklyDigest | None:
        return (
            await self.session.scalars(
                select(WeeklyDigest)
                .where(WeeklyDigest.tenant_id == self.ctx.tenant_id)
                .order_by(WeeklyDigest.week_start.desc())
                .limit(1)
            )
        ).one_or_none()

    async def for_week(self, week_start: datetime) -> WeeklyDigest | None:
        return (
            await self.session.scalars(
                select(WeeklyDigest).where(
                    WeeklyDigest.tenant_id == self.ctx.tenant_id,
                    WeeklyDigest.week_start == week_start,
                )
            )
        ).one_or_none()

    async def save(self, start: datetime, end: datetime, answer: dict[str, Any]) -> WeeklyDigest:
        await self.session.execute(
            insert(WeeklyDigest)
            .values(
                tenant_id=self.ctx.tenant_id,
                week_start=start,
                period_end=end,
                answer=answer,
            )
            .on_conflict_do_nothing(
                index_elements=[WeeklyDigest.tenant_id, WeeklyDigest.week_start]
            )
        )
        digest = await self.for_week(start)
        assert digest is not None
        return digest
