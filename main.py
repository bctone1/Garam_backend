import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from garam_backend.app.routers import register_routers
from core.config import UPLOAD_FOLDER
import uvicorn

load_dotenv()

app = FastAPI(debug=True)

# static files
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.mount("/file", StaticFiles(directory=UPLOAD_FOLDER), name="file")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 운영에서는 화이트리스트로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
register_routers(app, prefix=os.getenv("API_PREFIX", "/api"))

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        reload=bool(int(os.getenv("RELOAD", "0"))),
    )
