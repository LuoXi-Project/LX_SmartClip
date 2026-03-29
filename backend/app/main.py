import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.db.init_db import init_db
from app.api.config import router as config_router
from app.api.videos import router as videos_router
from app.api.clips import router as clips_router
from app.api.asr import router as asr_router
from app.api.vlm import router as vlm_router
from app.api.embed import router as embed_router
from app.api.process import router as process_router
from app.api.match import router as match_router
from app.api.tts import router as tts_router
from app.api.export import router as export_router
from app.api.chat import router as chat_router
from app.api.copy_gen import router as copy_gen_router
from app.api.subtitle import router as subtitle_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="LX SmartClip API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(videos_router)
app.include_router(clips_router)
app.include_router(asr_router)
app.include_router(vlm_router)
app.include_router(embed_router)
app.include_router(process_router)
app.include_router(match_router)
app.include_router(tts_router)
app.include_router(export_router)
app.include_router(chat_router)
app.include_router(copy_gen_router)
app.include_router(subtitle_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
