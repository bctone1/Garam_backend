from fastapi import APIRouter, FastAPI
from app.endpoints import (
    admin_user,
    chat,
    inquiry,
    knowledge,
    faq,
    model,
    system,
    analytics,
    llm,
    api_cost,
    notification,
    websocket,
    chat_history,
)

router = APIRouter()

router.include_router(admin_user.router)
router.include_router(inquiry.router)
router.include_router(chat.router)
router.include_router(knowledge.router)
router.include_router(faq.router)
router.include_router(model.router)
router.include_router(system.router)
router.include_router(analytics.router)
router.include_router(llm.router)
router.include_router(api_cost.router)
router.include_router(notification.router)
router.include_router(websocket.router)
router.include_router(chat_history.router)

def register_routers(app: FastAPI) -> None:
    app.include_router(router)
