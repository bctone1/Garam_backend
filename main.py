
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

from typing import List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for ws in self.active_connections:
            await ws.send_text(message)


ws_manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    print("🟢 WebSocket connected:", len(ws_manager.active_connections))

    try:
        while True:
            data = await websocket.receive_text()
            print(f"받은 메시지: {data}")

            # 🔥 모든 클라이언트에게 전송
            await ws_manager.broadcast(f"알림: {data}")

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        print("🔴 WebSocket disconnected:", len(ws_manager.active_connections))


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
