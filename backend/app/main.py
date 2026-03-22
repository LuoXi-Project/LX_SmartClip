from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.db.init_db import init_db
from app.api.config import router as config_router
from app.api.videos import router as videos_router
from app.api.clips import router as clips_router
from app.api.asr import router as asr_router
from app.api.vlm import router as vlm_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="LX SmartClip API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(videos_router)
app.include_router(clips_router)
app.include_router(asr_router)
app.include_router(vlm_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
