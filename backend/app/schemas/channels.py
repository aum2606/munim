from pydantic import BaseModel, Field

from app.schemas.auth import StrictRequest


class WhatsAppConnect(StrictRequest):
    # Meta's phone number id (digits), shown in the app's WhatsApp > API Setup page.
    phone_number_id: str = Field(pattern=r"^\d{5,32}$")
    display_phone: str | None = Field(default=None, max_length=24)
    access_token: str = Field(min_length=20, max_length=1024)


class WhatsAppStatus(BaseModel):
    connected: bool
    phone_number_id: str | None = None
    display_phone: str | None = None
    # False until the server has WHATSAPP_VERIFY_TOKEN and WHATSAPP_APP_SECRET: then Meta's
    # webhook is refused and no customer message can arrive.
    webhook_ready: bool
