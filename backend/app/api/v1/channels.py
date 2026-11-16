from fastapi import APIRouter, status

from app.core.config import Settings
from app.core.crypto import encrypt_credentials
from app.core.deps import CtxDep, OwnerDep, SessionDep, SettingsDep
from app.core.errors import ConflictError
from app.db.models import ChannelAccount
from app.repositories.channels import ChannelAccountRepository, tenant_for_phone_number_id
from app.schemas.channels import WhatsAppConnect, WhatsAppStatus

router = APIRouter(tags=["channels"])


def _status(settings: Settings, account: ChannelAccount | None) -> WhatsAppStatus:
    ready = bool(settings.whatsapp_verify_token and settings.whatsapp_app_secret)
    return WhatsAppStatus(
        connected=account is not None,
        phone_number_id=account.external_id if account else None,
        display_phone=account.display_phone if account else None,
        webhook_ready=ready,
    )


@router.get("/channels/whatsapp", response_model=WhatsAppStatus)
async def whatsapp_status(
    ctx: CtxDep, session: SessionDep, settings: SettingsDep
) -> WhatsAppStatus:
    return _status(settings, await ChannelAccountRepository(session, ctx).get())


@router.put("/channels/whatsapp", response_model=WhatsAppStatus)
async def connect_whatsapp(
    body: WhatsAppConnect, ctx: OwnerDep, session: SessionDep, settings: SettingsDep
) -> WhatsAppStatus:
    """Save the business's number and token. The token is encrypted and never returned."""
    owner = await tenant_for_phone_number_id(session, body.phone_number_id)
    if owner is not None and owner != ctx.tenant_id:
        raise ConflictError("This WhatsApp number is already connected to another business")
    account = await ChannelAccountRepository(session, ctx).save(
        body.phone_number_id,
        body.display_phone,
        encrypt_credentials(settings, {"access_token": body.access_token}),
    )
    return _status(settings, account)


@router.delete("/channels/whatsapp", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_whatsapp(ctx: OwnerDep, session: SessionDep) -> None:
    await ChannelAccountRepository(session, ctx).delete()
