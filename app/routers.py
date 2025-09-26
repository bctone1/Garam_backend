from fastapi import APIRouter, FastAPI
from app.endpoints import admin_user, chat, inquiry, knowledge, faq, model, system, analytics

router = APIRouter()

router.include_router(admin_user.router)
router.include_router(inquiry.router)
router.include_router(chat.router)
router.include_router(knowledge.router)
router.include_router(faq.router)
router.include_router(model.router)
router.include_router(system.router)
router.include_router(analytics.router)

def register_routers(app: FastAPI) -> None:
    app.include_router(router)

# def register_routers(app: FastAPI, prefix: str = "/app") -> None:
#     app.include_router(router, prefix=prefix)
