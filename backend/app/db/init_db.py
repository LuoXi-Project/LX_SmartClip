import aiosqlite
import os

DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "smartclip.db")
)

CREATE_VIDEOS = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    duration REAL,
    total_clips INTEGER DEFAULT 0,
    split_mode TEXT DEFAULT 'scene',
    status TEXT DEFAULT 'pending',
    upload_at TEXT NOT NULL
);
"""

CREATE_CLIPS = """
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    clip_path TEXT,
    start_time REAL,
    end_time REAL,
    duration REAL,
    asr_text TEXT,
    vlm_description TEXT,
    tags TEXT,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
"""

CREATE_CONFIG = """
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT,
    type TEXT DEFAULT 'string',
    label TEXT,
    options TEXT
);
"""

DEFAULT_CONFIG = [
    ("split_mode", "scene", "select", "cut mode", '["scene","fixed"]'),
    ("fixed_duration", "10", "number", "fixed duration(s)", None),
    ("scene_threshold", "0.4", "number", "scene threshold", None),
    ("vector_dimension", "1536", "number", "vector dimension", None),
    ("top_k", "12", "number", "top k", None),
    ("vlm_provider", "openai", "select", "vlm provider", '["openai"]'),
    (
        "vlm_base_url",
        "https://api.openai.com/v1",
        "string",
        "vlm base url",
        None,
    ),
    ("vlm_model", "gpt-4o", "string", "vlm model", None),
    ("vlm_api_key", "", "string", "vlm api key", None),
    ("tts_provider", "edge-tts", "select", "tts provider", '["edge-tts"]'),
    (
        "asr_model",
        "base",
        "select",
        "asr model size",
        '["tiny","base","small","medium","large"]',
    ),
]


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_VIDEOS)
        await db.execute(CREATE_CLIPS)
        await db.execute(CREATE_CONFIG)
        for key, value, type_, label, options in DEFAULT_CONFIG:
            await db.execute(
                "INSERT OR IGNORE INTO config (key, value, type, label, options) VALUES (?,?,?,?,?)",
                (key, value, type_, label, options),
            )
        await db.commit()
