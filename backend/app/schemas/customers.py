import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import Channel, Direction, QuoteStatus, SenderType


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    phone: str | None
    created_at: datetime


class ExportedMessage(BaseModel):
    direction: Direction
    sender_type: SenderType
    content: str
    created_at: datetime


class ExportedConversation(BaseModel):
    id: uuid.UUID
    channel: Channel
    created_at: datetime
    messages: list[ExportedMessage]


class ExportedQuoteLine(BaseModel):
    description: str
    qty: str
    unit_price_paise: int
    line_total_paise: int


class ExportedQuote(BaseModel):
    quote_number: str
    status: QuoteStatus
    total_paise: int
    created_at: datetime
    items: list[ExportedQuoteLine]


class CustomerExport(BaseModel):
    """Everything held about one customer, for their right of access (DPDP Act 2023)."""

    customer: CustomerOut
    conversations: list[ExportedConversation]
    quotes: list[ExportedQuote]
