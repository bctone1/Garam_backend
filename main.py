
import os, logging, uvicorn
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()  # 조건 없이 연결 허용
    try:
        while True:
            data = await websocket.receive_text()  # 어떤 메시지도 수신
            print(f"받은 메시지: {data}")

            # 그대로 다시 보내기 (echo)
            await websocket.send_text(f"echo: {data}")

    except WebSocketDisconnect:
        print("클라이언트 연결 종료")


os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.mount("/file", StaticFiles(directory=UPLOAD_FOLDER), name="file")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_routers(app)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5002")),
        reload=bool(int(os.getenv("RELOAD", "0"))),
    )
