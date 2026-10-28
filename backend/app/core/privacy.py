import asyncio
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.repositories.privacy import PrivacyRepository
from app.repositories.storage import protect_storage_write
from app.schemas.privacy import EraseCustomer, ErasureView


class PrivacyService:
    def __init__(self, session: AsyncSession, ctx: TenantContext, config: Settings) -> None:
        self.session, self.ctx, self.config = session, ctx, config
        self.repository = PrivacyRepository(
            session,
            ctx,
            (config.privacy_hash_key.get_secret_value() or config.secret_key.get_secret_value()),
        )

    async def erase(self, customer_id: UUID, body: EraseCustomer) -> ErasureView:
        if body.confirm_customer_id != customer_id:
            raise DomainError("Customer confirmation does not match the requested record", 409)
        erasure = await self.repository.erase(customer_id)
        await self.session.commit()
        return await self.finish_files(erasure.id)

    async def finish_files(self, erasure_id: UUID) -> ErasureView:
        await protect_storage_write(self.session, self.ctx)
        erasure = await self.repository.get(erasure_id, for_update=True)
        root = await asyncio.to_thread(Path(self.config.storage_dir).resolve)
        tenant_root = root / str(self.ctx.tenant_id)

        def remove_files(paths: list[str]) -> list[str]:
            remaining = []
            for stored in paths:
                path = Path(stored)
                path = (path if path.is_absolute() else root / path).resolve()
                if not path.is_relative_to(tenant_root):
                    remaining.append(stored)
                    continue
                try:
                    if (
                        re.fullmatch(r"[a-f0-9-]{36}-\*\.pdf", path.name)
                        and path.parent == tenant_root / "quotes"
                    ):
                        for version in path.parent.glob(path.name):
                            if not version.resolve().is_relative_to(tenant_root):
                                raise OSError("File escapes tenant storage")
                            version.unlink(missing_ok=True)
                    else:
                        path.unlink(missing_ok=True)
                except OSError:
                    remaining.append(stored)
            return remaining

        erasure.files = await asyncio.to_thread(remove_files, list(erasure.files))
        erasure.status = "pending_files" if erasure.files else "complete"
        await self.session.commit()
        return ErasureView(id=erasure.id, status=erasure.status, files_remaining=len(erasure.files))
