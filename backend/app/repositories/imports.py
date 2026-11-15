import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import TenantContext
from app.db.models import ImportJob, ImportStatus


class ImportJobRepository:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx

    async def add(
        self,
        *,
        filename: str,
        storage_path: str,
        headers: list[str],
        mapping: dict[str, str],
        row_count: int,
    ) -> ImportJob:
        job = ImportJob(
            tenant_id=self._ctx.tenant_id,
            filename=filename[:200],
            storage_path=storage_path,
            headers=headers,
            mapping=mapping,
            row_count=row_count,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> ImportJob | None:
        return await self._session.scalar(
            select(ImportJob).where(
                ImportJob.tenant_id == self._ctx.tenant_id, ImportJob.id == job_id
            )
        )

    @staticmethod
    def mark_committed(job: ImportJob) -> None:
        job.status = ImportStatus.COMMITTED
        job.committed_at = datetime.now(UTC)
