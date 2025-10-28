
import os, logging, uvicorn
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
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
