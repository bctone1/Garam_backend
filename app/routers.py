from fastapi import APIRouter, FastAPI
from garam_backend.app.endpoints import admin_user, chat, inquiry, knowledge, faq, model, system

router = APIRouter()

router.include_router(admin_user.router)
router.include_router(inquiry.router)
router.include_router(chat.router)
router.include_router(knowledge.router)
router.include_router(faq.router)
router.include_router(model.router)
router.include_router(system.router)


def register_routers(app: FastAPI, prefix: str = "/api") -> None:
    app.include_router(router, prefix=prefix)
