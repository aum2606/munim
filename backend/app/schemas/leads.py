from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.db.models.conversation import ConversationMode
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def display_estimated_value(self) -> str:
        from app.pricing.inr import format_inr

        return format_inr(self.estimated_value_paise)


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


class ModeChange(StrictModel):
    mode: ConversationMode


class StaffReply(StrictModel):
    content: str = Field(min_length=1, max_length=4000)
    external_id: str = Field(min_length=1, max_length=100)

    @field_validator("content")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value.strip()


class BusinessHours(StrictModel):
    hours: dict[str, list[str]] = Field(default_factory=dict, max_length=7)

    @field_validator("hours")
    @classmethod
    def valid_hours(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        from datetime import time

        days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
        for day, window in value.items():
            if day not in days or len(window) != 2:
                raise ValueError("Use weekday names and two HH:MM values")
            for entry in window:
                parsed = time.fromisoformat(entry)
                if parsed.tzinfo or len(entry) != 5:
                    raise ValueError("Use local HH:MM values")
        return value
