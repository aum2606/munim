import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    action: str
    target: str | None
    actor: str | None
