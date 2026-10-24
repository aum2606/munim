from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.lead import LeadStage
from app.schemas.knowledge import StrictModel


class LeadInput(StrictModel):
    messages: list[str]


class LeadOutput(StrictModel):
    summary: str = Field(max_length=1000)
    tags: list[str] = Field(max_length=10)
    buying_signal: int = Field(strict=True, ge=-20, le=20)


class HandoffInput(StrictModel):
    reason: str
    messages: list[str]


class HandoffOutput(StrictModel):
    summary: str = Field(min_length=1, max_length=1000)


class LeadView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    stage: LeadStage
    stage_override: bool
    score: int
    summary: str
    category: str
    requirements: dict[str, object]
    tags: list[str]
    estimated_value_paise: int
    assigned_to: UUID | None
    next_followup_at: datetime | None
    lost_reason: str | None
    source_channel: str


class LeadPatch(StrictModel):
    stage: LeadStage | None = None
    stage_override: bool | None = None
    assigned_to: UUID | None = None
    lost_reason: str | None = Field(default=None, max_length=500)
    next_followup_at: datetime | None = None


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_type: str
    from_value: str | None
    to_value: str | None
    actor: str
    note: str
    created_at: datetime


class FollowupPolicy(StrictModel):
    enabled: bool = True
    no_reply_days: int = Field(default=2, ge=1, le=90)
    quote_reminder_days: int = Field(default=1, ge=1, le=30)
    reengage_days: int = Field(default=14, ge=2, le=365)


class FollowupView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    lead_id: UUID
    scheduled_at: datetime
    status: str
    kind: str
    draft_text: str
    requires_template: bool


class FollowupAction(StrictModel):
    action: Literal["approve", "cancel"]


class DraftView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    content: str
    status: str


class HandoffView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    reason: str
    summary: str
    status: str
