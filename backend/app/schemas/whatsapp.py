from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.db.models.channel import AccountStatus, DeliveryStatus
from app.schemas.knowledge import StrictModel


class ConnectWhatsApp(StrictModel):
    phone_number_id: str = Field(pattern=r"^\d{5,30}$")
    business_account_id: str = Field(pattern=r"^\d{5,30}$")
    access_token: SecretStr = Field(min_length=10, max_length=4096)


class AccountView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    external_id: str
    business_account_id: str
    status: AccountStatus


class AccountChange(StrictModel):
    status: AccountStatus


class TemplateView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    name: str
    language: str
    status: str
    body_text: str
    usable: bool


class DeliveryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    message_id: UUID
    status: DeliveryStatus
    attempts: int
    last_error: str | None
    provider_message_id: str | None
    next_attempt_at: datetime
    conversation_id: UUID | None = None
    content_preview: str = ""


class ConsentChange(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    opted_in: bool
    note: str = Field(min_length=3, max_length=500)


class ConsentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    opted_in_at: datetime | None
    opted_out: bool
    consent_note: str
    freeform_allowed: bool = False


class MetaText(BaseModel):
    body: str = Field(max_length=4000)


class MetaMedia(BaseModel):
    id: str = Field(max_length=256)
    mime_type: str = Field(default="", max_length=100)
    caption: str = Field(default="", max_length=4000)
    filename: str = Field(default="", max_length=200)


class MetaReply(BaseModel):
    id: str = Field(default="", max_length=256)
    title: str = Field(default="", max_length=200)


class MetaInteractive(BaseModel):
    button_reply: MetaReply | None = None
    list_reply: MetaReply | None = None


class MetaButton(BaseModel):
    text: str = Field(max_length=200)


class MetaMessage(BaseModel):
    id: str = Field(min_length=1, max_length=512)
    from_: str = Field(alias="from", pattern=r"^\d{7,15}$")
    timestamp: str = Field(pattern=r"^\d{1,12}$")
    type: str = Field(max_length=40)
    text: MetaText | None = None
    image: MetaMedia | None = None
    document: MetaMedia | None = None
    interactive: MetaInteractive | None = None
    button: MetaButton | None = None


class MetaStatus(BaseModel):
    id: str = Field(min_length=1, max_length=512)
    status: str = Field(max_length=40)


class MetaMetadata(BaseModel):
    phone_number_id: str = Field(pattern=r"^\d{5,30}$")


class MetaValue(BaseModel):
    metadata: MetaMetadata | None = None
    messages: list[MetaMessage] = Field(default_factory=list, max_length=100)
    statuses: list[MetaStatus] = Field(default_factory=list, max_length=100)


class MetaChange(BaseModel):
    field: str
    value: MetaValue


class MetaEntry(BaseModel):
    id: str = Field(pattern=r"^\d{5,30}$")
    changes: list[MetaChange] = Field(default_factory=list, max_length=100)


class MetaWebhook(BaseModel):
    object: Literal["whatsapp_business_account"]
    entry: list[MetaEntry] = Field(max_length=100)


class ParsedInbound(StrictModel):
    provider_id: str
    wa_id: str
    timestamp: datetime
    content: str
    content_type: str
    attachments: list[dict[str, str]]


class DeliveryResolution(StrictModel):
    confirmed_not_sent: bool = False
    provider_message_id: str | None = Field(default=None, pattern=r"^wamid\..{1,500}$")


class SetupView(StrictModel):
    callback_url: str
    encryption_ready: bool
    webhook_ready: bool
    api_version_ready: bool


class FollowupOptions(StrictModel):
    conversation_id: UUID
    consent: ConsentView
    templates: list[TemplateView]
