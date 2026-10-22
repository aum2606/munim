from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.knowledge import DocumentStatus, SourceType


class DocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    source_type: SourceType
    status: DocumentStatus
    error: str | None


class FAQInput(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=2000)
