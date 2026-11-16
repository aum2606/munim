import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AgentRunStatus, Channel, ConversationMode, Direction, SenderType
from app.schemas.auth import StrictRequest


class PlaygroundSend(StrictRequest):
    conversation_id: uuid.UUID | None = None  # omit to start a new test conversation
    text: str = Field(min_length=1, max_length=2000)


class PlaygroundSent(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: Direction
    sender_type: SenderType
    content: str
    language: str | None
    intent: str | None
    reply_to_id: uuid.UUID | None
    quote_id: uuid.UUID | None  # set when this message delivers a quotation
    kind: str  # text or audio (a voice note, shown as its transcript)
    transcript_confidence: float | None
    delivery_status: str | None  # sent, delivered, read, failed or window_closed
    delivery_error: str | None
    created_at: datetime


class StaffReply(StrictRequest):
    text: str = Field(min_length=1, max_length=2000)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: Channel
    mode: ConversationMode
    customer_name: str | None = None
    customer_phone: str | None = None
    last_message: str | None = None  # a short preview for the inbox list
    # False once 24 hours have passed since the customer last wrote: WhatsApp then blocks
    # free-form replies, so the dashboard warns before staff type one.
    can_reply: bool = True
    last_customer_msg_at: datetime | None
    last_business_msg_at: datetime | None
    created_at: datetime


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent: str
    provider: str | None
    model: str | None
    prompt_version: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    tool_calls: list[dict[str, Any]]
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    status: AgentRunStatus
    error: str | None
    created_at: datetime
