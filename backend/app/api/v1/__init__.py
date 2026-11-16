from fastapi import APIRouter

from app.api.v1 import auth, catalog, chat, knowledge, quotes, settings, users

router = APIRouter()
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(catalog.router)
router.include_router(knowledge.router)
router.include_router(chat.router)
router.include_router(quotes.router)
router.include_router(settings.router)
