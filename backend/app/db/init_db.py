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
    thumbnail_path TEXT,
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
    ("split_mode", "scene", "select", "分割模式", '["scene","fixed"]'),
    ("fixed_duration", "10", "number", "固定分割时长（秒）", None),
    ("scene_threshold", "0.4", "number", "场景检测阈值", None),
    ("vector_dimension", "1536", "number", "向量维度", None),
    ("top_k", "12", "number", "召回数量 top_k", None),
    ("vlm_provider", "openai", "select", "视觉模型提供商", '["openai"]'),
    (
        "vlm_base_url",
        "https://api.openai.com/v1",
        "string",
        "视觉模型 API 地址",
        None,
    ),
    ("vlm_model", "gpt-4o", "string", "视觉模型名称", None),
    ("vlm_api_key", "", "string", "视觉模型 API 密钥", None),
    ("embedding_provider", "openai", "select", "向量嵌入提供商", '["openai"]'),
    (
        "embedding_base_url",
        "https://api.openai.com/v1",
        "string",
        "向量嵌入 API 地址",
        None,
    ),
    ("embedding_model", "text-embedding-3-small", "string", "向量嵌入模型名称", None),
    ("embedding_api_key", "", "string", "向量嵌入 API 密钥", None),
    ("tts_provider", "edge-tts", "select", "TTS 提供商", '["edge-tts","openai","bailian","volcengine","gpt-sovits","index-tts","custom-get"]'),
    ("asr_provider", "whisper", "select", "ASR 提供商", '["whisper","openai"]'),
    (
        "asr_model",
        "base",
        "select",
        "ASR 模型大小 (本地 Whisper)",
        '["tiny","base","small","medium","large"]',
    ),
    ("asr_base_url", "https://api.openai.com/v1", "string", "ASR API 地址", None),
    ("asr_api_key", "", "string", "ASR API 密钥", None),
    ("asr_openai_model", "whisper-1", "string", "ASR 模型名称 (OpenAI 协议)", None),
    ("llm_model", "gpt-4o-mini", "string", "大语言模型（精排）", None),
    ("match_top_k", "12", "number", "初筛数量 top_k", None),
    ("match_top_n", "5", "number", "推荐数量 top_n", None),
    ("tts_voice", "zh-CN-XiaoxiaoNeural", "string", "TTS 语音角色", None),
    ("tts_rate", "+0%", "string", "TTS 语速 (如 +0%/-20%)", None),
    ("tts_volume", "+0%", "string", "TTS 音量 (如 +0%/+10%)", None),
    ("tts_base_url", "", "string", "TTS API 地址", None),
    ("tts_api_key", "", "string", "TTS API 密钥", None),
    ("tts_model", "", "string", "TTS 模型名", None),
    ("tts_format", "mp3", "select", "TTS 音频格式", '["mp3","wav","pcm","ogg"]'),
    ("bailian_app_key", "", "string", "百炼 App-Key", None),
    ("volcengine_app_id", "", "string", "火山 App ID", None),
    ("volcengine_token", "", "string", "火山 Token", None),
    ("volcengine_cluster", "volcano_tts", "string", "火山 Cluster", None),
    ("gsv_ref_audio", "", "string", "参考音频路径", None),
    ("gsv_ref_text", "", "string", "参考音频文本", None),
    ("gsv_lang", "zh", "select", "语言", '["zh","en","ja","auto"]'),
    ("index_tts_ref_audio", "", "string", "IndexTTS 参考音频路径", None),
    ("custom_tts_method", "GET", "select", "请求方法", '["GET","POST"]'),
    ("custom_tts_url", "", "string", "请求 URL (支持 {text} 占位符)", None),
    ("custom_tts_headers", "", "string", "请求头 JSON (可选，如 {\"Authorization\":\"Bearer xxx\"})", None),
    ("custom_tts_body", "", "string", "POST 请求体 JSON 模板 (支持 {text} 占位符)", None),
    ("custom_tts_response_type", "binary", "select", "响应类型", '["binary","json"]'),
    ("custom_tts_audio_key", "", "string", "响应 JSON 音频字段路径 (支持 a.b.0.c)", None),
    ("frame_fps", "1", "number", "抽帧帧率 (帧/秒)", None),
    ("vlm_context_length", "8192", "number", "VLM 上下文长度 (tokens)", None),
    ("vlm_max_images_per_batch", "10", "number", "VLM 单次最大图片数量", None),
    ("vlm_concurrency", "3", "number", "VLM 并发数量", None),
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
