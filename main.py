# main.py (WebSocket 포함, lifespan 버전)
import os, logging, uvicorn
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import register_routers
from core.config import UPLOAD_FOLDER
from core.scheduler import init_scheduler  # APScheduler 초기화

load_dotenv()
log = logging.getLogger("uvicorn")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    sched = init_scheduler()
    sched.start()
    app.state.scheduler = sched
    log.info("APScheduler started")
    try:
        yield
    finally:
        # shutdown
        sched.shutdown(wait=False)
        log.info("APScheduler stopped")

app = FastAPI(debug=True, lifespan=lifespan)

# 업로드 폴더 생성
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.mount("/file", StaticFiles(directory=UPLOAD_FOLDER), name="file")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 기존 라우터 등록
register_routers(app)

# ----------------------------
# WebSocket 라우터 추가
# ----------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    log.info("WebSocket client connected")
    try:
        while True:
            data = await websocket.receive_text()
            log.info(f"Received: {data}")
            await websocket.send_text(f"Server echo: {data}")
    except Exception as e:
        log.warning(f"WebSocket disconnected: {e}")

# ----------------------------
# 앱 실행
# ----------------------------
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5002")),
        reload=bool(int(os.getenv("RELOAD", "0"))),
    )
