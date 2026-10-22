from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    user_id: UUID | None = None
    role: str = "staff"
