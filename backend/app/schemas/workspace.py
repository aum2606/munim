from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.conversation import GapStatus


class GapView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    question: str
    occurrences: int
    status: GapStatus
    answer_text: str | None


class GapAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


class AgentRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    message_id: UUID | None
    agent: str
    model: str
    input: dict[str, Any]
    output: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    status: str
    error: str | None
