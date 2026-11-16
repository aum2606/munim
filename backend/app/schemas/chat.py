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
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: Channel
    mode: ConversationMode
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
