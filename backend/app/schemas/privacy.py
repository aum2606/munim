from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

NOTICE_VERSION = "2026-10-28"


class EraseCustomer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_customer_id: UUID
    retention_reviewed: Literal[True]


class ErasureView(BaseModel):
    id: UUID
    status: str
    files_remaining: int
