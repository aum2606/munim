from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.tenant import TenantContext
from app.repositories.identity import TenantRepository
from app.repositories.storage import protect_storage_write
from app.schemas.quote_profile import QuoteProfile
from app.schemas.quotes import QuoteSettings


class QuoteSettingsService:
    def __init__(self, session: AsyncSession, ctx: TenantContext, config: Settings) -> None:
        self.session, self.ctx, self.config = session, ctx, config
        self.tenants = TenantRepository(session, ctx)

    async def update(self, body: QuoteSettings) -> QuoteSettings:
        settings = await self.tenants.settings()
        for key, value in body.model_dump().items():
            setattr(settings, key, value)
        await self.session.flush()
        return QuoteSettings.model_validate(settings)

    async def profile(self, body: QuoteProfile) -> QuoteProfile:
        tenant = await self.tenants.get()
        for key, value in body.model_dump().items():
            setattr(tenant, key, value)
        await self.session.flush()
        return QuoteProfile.model_validate(tenant)

    async def logo(self, content: bytes) -> None:
        if len(content) > 2 * 1024 * 1024:
            raise DomainError("Logo must be a PNG or JPEG of at most 2 MB")
        await protect_storage_write(self.session, self.ctx)
        relative = Path(str(self.ctx.tenant_id)) / "logos" / (str(uuid4()) + ".png")

        def save() -> None:
            try:
                image: Image.Image = Image.open(BytesIO(content))
                if image.format not in {"PNG", "JPEG"} or max(image.size) > 2000:
                    raise DomainError("Logo must be a PNG/JPEG of at most 2000 pixels per side")
                image.load()
                image = image.convert("RGBA")
                image.thumbnail((400, 200))
                image.info.clear()
                path = Path(self.config.storage_dir) / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                image.save(path, format="PNG")
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
                raise DomainError("Logo could not be read") from error

        await run_in_threadpool(save)
        (await self.tenants.get()).logo_url = str(relative)
        await self.session.flush()
