from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.conversation import ConversationMode, ConversationStatus, Direction, SenderType


class WidgetStart(BaseModel):
    key: str = Field(min_length=20, max_length=128)


class WidgetSessionView(BaseModel):
    session_id: UUID
    conversation_id: UUID
    token: str
    business_name: str


class WidgetMessage(BaseModel):
    session_id: UUID
    external_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=4000)


class MessageView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    direction: Direction
    sender_type: SenderType
    content: str
    language: str | None
    intent: str | None
    attachments: list[dict[str, Any]]
    agent_run_id: UUID | None
    created_at: datetime


class ConversationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    channel: str
    mode: ConversationMode
    status: ConversationStatus
    last_customer_msg_at: datetime | None
    last_business_msg_at: datetime | None


class ReplyButton(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    title: str = Field(min_length=1, max_length=20)
