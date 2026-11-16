import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import FollowUpStatus
from app.schemas.auth import StrictRequest


class FollowUpOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    quote_id: uuid.UUID
    quote_number: str | None = None
    customer_name: str | None = None
    draft: str
    status: FollowUpStatus
    # False when WhatsApp would refuse the message (24 hours since the customer wrote): copy the
    # text and send it from your own phone instead.
    can_send: bool = True
    created_at: datetime


class FollowUpSend(StrictRequest):
    text: str | None = Field(default=None, min_length=1, max_length=2000)  # edited draft
