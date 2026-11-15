import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DocumentSource, DocumentStatus, GapStatus
from app.schemas.auth import StrictRequest


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: DocumentSource
    status: DocumentStatus
    error: str | None
    created_at: datetime


class FaqIn(StrictRequest):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=4000)


class FaqOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    status: DocumentStatus


class GapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    occurrences: int
    status: GapStatus
    answer_text: str | None
    created_at: datetime


class GapAnswer(StrictRequest):
    answer: str = Field(min_length=1, max_length=4000)
