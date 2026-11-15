import enum
import uuid
from dataclasses import dataclass


class Role(enum.StrEnum):
    OWNER = "owner"
    STAFF = "staff"


@dataclass(frozen=True)
class TenantContext:
    """Who is acting, and for which tenant. Every repository takes one and filters by it.

    user_id/role are None for system actors (worker, webhooks, customer-triggered work).
    """

    tenant_id: uuid.UUID
    user_id: uuid.UUID | None = None
    role: Role | None = None

    @classmethod
    def system(cls, tenant_id: uuid.UUID) -> "TenantContext":
        return cls(tenant_id=tenant_id)
