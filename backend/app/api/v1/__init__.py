from fastapi import APIRouter, Depends

from app.api.v1 import (
    audit,
    auth,
    catalog,
    channels,
    chat,
    customers,
    followups,
    knowledge,
    metrics,
    quotes,
    settings,
    users,
)
from app.core.ratelimit import rate_limit

# Every signed-in call counts against its business: a runaway script cannot starve the others.
router = APIRouter(dependencies=[Depends(rate_limit("api", 300, 60, by="tenant"))])
router.include_router(auth.router)
router.include_router(audit.router)
router.include_router(users.router)
router.include_router(catalog.router)
router.include_router(knowledge.router)
router.include_router(channels.router)
router.include_router(chat.router)
router.include_router(customers.router)
router.include_router(followups.router)
router.include_router(metrics.router)
router.include_router(quotes.router)
router.include_router(settings.router)
