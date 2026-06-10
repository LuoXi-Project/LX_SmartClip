import aiosqlite
import os

from app.db.database import DB_PATH
from app.utils.paths import to_stored_path

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
    asr_segments TEXT,
    vlm_description TEXT,
    tags TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
"""

CREATE_REPLICA_TEMPLATES = """
CREATE TABLE IF NOT EXISTS replica_templates (
    id TEXT PRIMARY KEY,
    name TEXT,
    source_video_id TEXT NOT NULL,
    source_url TEXT,
    template_json TEXT NOT NULL,
    template_guide TEXT NOT NULL,
    pace TEXT,
    tone TEXT,
    structure_json TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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

CREATE_PROCESS_TASKS = """
CREATE TABLE IF NOT EXISTS process_tasks (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step TEXT,
    progress_json TEXT,
    metrics_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
"""

CREATE_AGENT_SESSIONS = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '未命名项目',
    workspace_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_AGENT_MESSAGES = """
CREATE TABLE IF NOT EXISTS agent_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
);
"""

CREATE_AGENT_PENDING_CONFIRMS = """
CREATE TABLE IF NOT EXISTS agent_pending_confirms (
    call_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    risk TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
);
"""

CREATE_SUMMARY_TEMPLATES = """
CREATE TABLE IF NOT EXISTS summary_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    system_prompt TEXT NOT NULL,
    user_prompt_template TEXT NOT NULL,
    output_schema_hint TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_VIDEO_SUMMARIES = """
CREATE TABLE IF NOT EXISTS video_summaries (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    template_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done',
    input_fingerprint TEXT,
    summary_json TEXT,
    summary_markdown TEXT,
    prompt_snapshot_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(id),
    FOREIGN KEY (template_id) REFERENCES summary_templates(id)
);
"""

CREATE_VIDEO_SUMMARY_VERSIONS = """
CREATE TABLE IF NOT EXISTS video_summary_versions (
    id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    source TEXT NOT NULL,
    content_json TEXT,
    content_markdown TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (summary_id) REFERENCES video_summaries(id)
);
"""

CREATE_FILM_COMMENTARY_JOBS = """
CREATE TABLE IF NOT EXISTS film_commentary_jobs (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step TEXT,
    mode TEXT NOT NULL DEFAULT 'precise',
    style TEXT NOT NULL DEFAULT 'suspense',
    target_duration_sec INTEGER NOT NULL DEFAULT 300,
    auto_render INTEGER NOT NULL DEFAULT 1,
    include_subtitle INTEGER NOT NULL DEFAULT 1,
    prompt_overrides_json TEXT,
    progress_json TEXT,
    error_message TEXT,
    clip_summaries_json TEXT,
    storyline_json TEXT,
    sentences_json TEXT,
    alignments_json TEXT,
    plan_json TEXT,
    output_path TEXT,
    output_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
"""

CREATE_VIDEO_SMART_OUTLINES = """
CREATE TABLE IF NOT EXISTS video_smart_outlines (
    video_id TEXT PRIMARY KEY,
    outline_markdown TEXT NOT NULL DEFAULT '',
    topics_json TEXT NOT NULL DEFAULT '[]',
    clip_scores_json TEXT NOT NULL DEFAULT '[]',
    meta_json TEXT,
    max_clips INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
"""

DEFAULT_CONFIG = [
    ("split_mode", "scene", "select", "分割模式", '["scene","fixed","hybrid"]'),
    ("fixed_duration", "10", "number", "固定分割时长（秒）", None),
    ("scene_threshold", "0.4", "number", "场景检测阈值", None),
    ("scene_min_scene_len", "30", "number", "最小镜头长度（帧）", None),
    ("hybrid_max_segment_sec", "60", "number", "混合模式单镜头最长（秒）", None),
    # 切分性能相关参数（FFmpeg / 分段吞吐）
    ("cut_mode", "fast", "select", "切割模式（速度/精度）", '["fast","precise"]'),
    ("stream_copy", "true", "select", "视频流复制（copy）", '["false","true"]'),
    ("stream_copy_audio", "true", "select", "音频流复制（copy）", '["false","true"]'),
    ("split_max_workers", "2", "number", "切分并行任务数", None),
    ("ffmpeg_threads_per_job", "1", "number", "每个 ffmpeg 的线程数", None),
    ("quiet_split", "true", "select", "安静切分（减少日志/进度输出）", '["true","false"]'),
    # 切分/转码输出参数（FFmpeg）
    ("clip_container", "mp4", "select", "切分输出格式（容器）", '["mp4","mov","mkv","webm"]'),
    ("clip_vcodec", "libx264", "select", "视频编码器", '["libx264","libx265","h264_nvenc","hevc_nvenc","libvpx-vp9","copy"]'),
    ("clip_acodec", "aac", "select", "音频编码器", '["aac","libopus","copy"]'),
    ("clip_preset", "veryfast", "select", "编码 preset（速度/质量）", '["ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow"]'),
    ("clip_crf", "18", "number", "视频质量参数（x264/x265=CRF，NVENC=CQ，0~51 越小越清晰）", None),
    ("clip_video_bitrate_kbps", "0", "number", "视频码率（kbps，0=使用 CRF）", None),
    ("clip_audio_bitrate_kbps", "128", "number", "音频码率（kbps）", None),
    ("clip_g", "48", "number", "GOP 长度（关键帧间隔）", None),
    ("clip_keyint_min", "48", "number", "最小关键帧间隔（x264/x265）", None),
    ("clip_sc_threshold", "0", "number", "场景切换阈值（x264/x265，0=关闭自动插入）", None),
    ("clip_fps", "0", "number", "输出帧率（fps，0=跟随源）", None),
    ("clip_scale_width", "0", "number", "输出宽度（px，0=不限制）", None),
    ("clip_scale_height", "0", "number", "输出高度（px，0=不限制）", None),
    ("clip_pix_fmt", "yuv420p", "select", "像素格式（兼容性）", '["yuv420p","yuv422p","yuv444p"]'),
    # 成片导出（字幕烧录 / 原声成片）：与切片分离，禁止 stream copy，保证时间轴一致
    ("export_container", "mp4", "select", "成片输出格式（容器）", '["mp4","mov","mkv","webm"]'),
    (
        "export_backend",
        "moviepy",
        "select",
        "成片导出后端（ffmpeg/moviepy）",
        '["moviepy","ffmpeg"]',
    ),
    (
        "export_gpu",
        "false",
        "select",
        "成片优先使用 GPU 编码（NVENC，失败自动回退 CPU）",
        '["false","true"]',
    ),
    (
        "export_vcodec",
        "libx264",
        "select",
        "成片视频编码器",
        '["libx264","libx265","h264_nvenc","hevc_nvenc","libvpx-vp9"]',
    ),
    ("export_acodec", "aac", "select", "成片音频编码器", '["aac","libopus"]'),
    (
        "export_preset",
        "fast",
        "select",
        "成片编码 preset（速度/质量）",
        '["ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow"]',
    ),
    ("export_crf", "20", "number", "成片视频 CRF（0~51）", None),
    ("export_video_bitrate_kbps", "0", "number", "成片视频码率（kbps，0=使用 CRF）", None),
    ("export_audio_bitrate_kbps", "192", "number", "成片音频码率（kbps）", None),
    ("export_g", "48", "number", "成片 GOP 长度（关键帧间隔）", None),
    ("export_keyint_min", "48", "number", "成片最小关键帧间隔（x264/x265）", None),
    ("export_sc_threshold", "0", "number", "成片场景切换阈值（x264/x265）", None),
    ("export_fps", "0", "number", "成片输出帧率（0=跟随源）", None),
    ("export_scale_width", "0", "number", "成片输出宽度（px，0=不限制）", None),
    ("export_scale_height", "0", "number", "成片输出高度（px，0=不限制）", None),
    ("export_pix_fmt", "yuv420p", "select", "成片像素格式", '["yuv420p","yuv422p","yuv444p"]'),
    ("vector_dimension", "1024", "number", "向量维度", None),
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
    (
        "embedding_provider",
        "openai",
        "select",
        "向量嵌入提供商",
        '["openai","siliconflow","deepseek","volcengine","custom"]',
    ),
    (
        "embedding_base_url",
        "https://api.openai.com/v1",
        "string",
        "向量嵌入 API 地址",
        None,
    ),
    ("embedding_model", "text-embedding-3-small", "string", "向量嵌入模型名称", None),
    ("embedding_api_key", "", "string", "向量嵌入 API 密钥", None),
    ("embedding_concurrency", "3", "number", "Embedding 并发数量", None),
    ("tts_provider", "edge-tts", "select", "TTS 提供商", '["edge-tts","openai","bailian","volcengine","gpt-sovits","index-tts","custom-get"]'),
    ("tts_concurrency", "3", "number", "TTS 并发数量", None),
    ("asr_provider", "whisper", "select", "ASR 提供商", '["whisper","openai","bailian"]'),
    (
        "asr_model",
        "base",
        "select",
        "ASR 模型大小 (本地 Whisper)",
        '["tiny","base","small","medium","large"]',
    ),
    ("asr_base_url", "https://api.openai.com/v1", "string", "ASR API 地址", None),
    ("asr_api_key", "", "string", "ASR API 密钥", None),
    ("asr_openai_model", "whisper-1", "string", "ASR 模型名称 (OpenAI/百炼)", None),
    (
        "asr_openai_transcriptions_path",
        "auto",
        "select",
        "OpenAI ASR 转写接口路径",
        '["auto","audio","v1_audio"]',
    ),
    (
        "asr_language",
        "zh",
        "string",
        "ASR 语言代码（ISO 639-1；留空为自动检测；可与各服务商文档自行对齐）",
        None,
    ),
    ("asr_concurrency", "1", "number", "ASR 并发数量", None),
    ("llm_base_url", "https://api.openai.com/v1", "string", "LLM API 地址", None),
    ("llm_api_key", "", "string", "LLM API 密钥", None),
    ("llm_model", "gpt-4o-mini", "string", "大语言模型（精排）", None),
    ("llm_temperature", "0.7", "number", "LLM 温度", None),
    ("llm_max_tokens", "20480", "number", "LLM 最大输出 tokens", None),
    ("llm_max_context_tokens", "128000", "number", "LLM 最大输入上下文 tokens", None),
    ("llm_concurrency", "3", "number", "LLM 并发数量", None),
    (
        "pexels_api_key",
        "",
        "string",
        "Pexels API Key（文案素材成片）",
        None,
    ),
    (
        "pixabay_api_key",
        "",
        "string",
        "Pixabay API Key（文案素材成片，见 https://pixabay.com/api/docs/ ）",
        None,
    ),
    (
        "unsplash_access_key",
        "",
        "string",
        "Unsplash Access Key（文案素材成片，见 https://unsplash.com/developers ）",
        None,
    ),
    (
        "stock_media_http_proxy",
        "",
        "string",
        "在线素材 HTTP 代理（可选；留空直连，不受系统代理影响）",
        None,
    ),
    (
        "jianying_draft_parent_dir",
        "",
        "string",
        "剪映草稿解压目录（可选；见说明）",
        None,
    ),
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
    ("frame_concurrency", "3", "number", "抽帧并发数量", None),
    ("frame_target_pixels", "1280", "number", "抽帧目标像素 (长边像素，0=不压制)", None),
    ("vlm_context_length", "65536", "number", "VLM 上下文长度 (tokens)", None),
    ("vlm_max_images_per_batch", "10", "number", "VLM 单次最大图片数量", None),
    ("vlm_concurrency", "3", "number", "VLM 并发数量", None),
    # 卡密（仅通过 /api/license 读写，不在 /api/config 中暴露）
    ("license_card", "", "string", "卡密", None),
    # 新手指引（/api/ui/onboarding 读写，不在设置页展示）
    ("ui_onboarding_v1", "", "string", "新手指引状态（内部）", None),
]

DEFAULT_SUMMARY_TEMPLATES = [
    (
        "default_note_zh",
        "笔记助手（中文·推荐）",
        "StageA 分段 JSON 摘要 + StageB 合并为一篇 Markdown；中文为主，支持目录、时间跳转与截图占位等版式开关。",
        "\n".join(
            [
                "你是一个专业的笔记助手，擅长将视频转录内容整理成清晰、有条理且信息丰富的笔记。",
                "",
                "语言：笔记内容使用中文；专有名词、技术术语、品牌与人名可保留英文。",
                "纪律：基于输入总结，禁止编造；数学公式用 LaTeX，便于 Markdown 渲染。",
                "排版：在 JSON 的字符串字段中可使用 Markdown；避免「1. **标题**」被误解析为有序列表，",
                "需要编号加粗时用「1\\\\. **标题**」或「## 1. 标题」。",
                "分阶段任务中请严格输出 JSON，并符合 schema_hint；不要输出多余解释或 Markdown 代码块包裹。",
            ]
        ),
        "\n".join(
            [
                "视频标题：{{video_title}}",
                "视频标签：{{tags}}",
                "",
                "【用户目标】",
                "{{user_goal}}",
                "",
                "【偏好/约束（可选）】",
                "{{extra_instructions}}",
                "",
                "说明：先对超长内容做 StageA 分段摘要，再按 overview / chapters / highlights 分块合并；",
                "字符串字段内可含 Markdown；章节正文中的时间锚点与截图提示见各 Stage 说明。",
            ]
        ),
        "\n".join(
            [
                "{",
                '  "title": "string",',
                '  "overview": "string",',
                '  "chapters": [',
                "    {",
                '      "title": "string",',
                '      "summary": "string",',
                '      "key_points": ["string"],',
                '      "evidence": ["string"]',
                "    }",
                "  ],",
                '  "key_points": ["string"],',
                '  "highlights": ["string"],',
                '  "quotes": ["string"],',
                '  "action_items": ["string"],',
                '  "tags": ["string"]',
                "}",
            ]
        ),
    ),
    (
        "default_general",
        "通用视频总结（推荐）",
        "StageA 输出分段 JSON，StageB 合并为整篇 Markdown 笔记。",
        "你是专业内容分析与总结助手。你擅长把口播/对白与画面信息整理为结构化总结。输出必须真实、可追溯、避免编造。",
        "\n".join(
            [
                "请基于提供的视频内容进行总结。",
                "",
                "【用户目标】",
                "{{user_goal}}",
                "",
                "【总结方式】",
                "- 先对超长内容按片段窗口做“分段摘要（StageA）”，再合并成“最终总结（StageB）”。",
                "- 对关键结论标注依据（尽量引用片段时间范围或原句/画面描述）。",
                "",
                "【输出要求】",
                "- 以 JSON 输出，严格匹配 schema_hint。",
                "- 不要输出多余解释，不要使用 Markdown code fence。",
                "",
                "【偏好/约束（可选）】",
                "{{extra_instructions}}",
            ]
        ),
        "\n".join(
            [
                "{",
                '  "title": "string",',
                '  "overview": "string",',
                '  "chapters": [',
                "    {",
                '      "title": "string",',
                '      "summary": "string",',
                '      "key_points": ["string"],',
                '      "evidence": ["string"]',
                "    }",
                "  ],",
                '  "key_points": ["string"],',
                '  "highlights": ["string"],',
                '  "quotes": ["string"],',
                '  "action_items": ["string"],',
                '  "tags": ["string"]',
                "}",
            ]
        ),
    ),
    (
        "default_asr_only",
        "仅基于字幕/ASR 总结",
        "适用于口播/访谈类；忽略画面描述，只用台词做结构化总结。",
        "你是专业内容分析与总结助手。只基于字幕/ASR 进行总结，禁止凭空补充画面信息。",
        "{{base_user_prompt}}",
        "{{base_schema_hint}}",
    ),
    (
        "default_vlm_only",
        "仅基于画面/VLM 总结",
        "适用于无对白/画面为主；只用视觉描述做结构化总结。",
        "你是专业内容分析与总结助手。只基于画面/VLM 描述进行总结，禁止臆测台词/对白。",
        "{{base_user_prompt}}",
        "{{base_schema_hint}}",
    ),
]


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_VIDEOS)
        await db.execute(CREATE_CLIPS)
        await db.execute(CREATE_REPLICA_TEMPLATES)
        await db.execute(CREATE_CONFIG)
        await db.execute(CREATE_PROCESS_TASKS)
        await db.execute(CREATE_AGENT_SESSIONS)
        await db.execute(CREATE_AGENT_MESSAGES)
        await db.execute(CREATE_AGENT_PENDING_CONFIRMS)
        await db.execute(CREATE_SUMMARY_TEMPLATES)
        await db.execute(CREATE_VIDEO_SUMMARIES)
        await db.execute(CREATE_VIDEO_SUMMARY_VERSIONS)
        await db.execute(CREATE_VIDEO_SMART_OUTLINES)
        await db.execute(CREATE_FILM_COMMENTARY_JOBS)
        # 兼容旧库：film_commentary_jobs 补 prompt_overrides_json
        try:
            cur = await db.execute("PRAGMA table_info(film_commentary_jobs)")
            film_cols = [str(r[1]) for r in await cur.fetchall()]
            if "prompt_overrides_json" not in film_cols:
                await db.execute(
                    "ALTER TABLE film_commentary_jobs ADD COLUMN prompt_overrides_json TEXT"
                )
        except Exception:
            pass
        # 旧版分块表已废弃，启动时删除（若存在）
        try:
            await db.execute("DROP TABLE IF EXISTS video_summary_sections")
        except Exception:
            pass

        # 兼容旧库：replica_templates 补列（SQLite 不支持 IF NOT EXISTS ADD COLUMN）
        try:
            cur = await db.execute("PRAGMA table_info(replica_templates)")
            cols = [str(r[1]) for r in await cur.fetchall()]  # (cid, name, type, notnull, dflt_value, pk)
            if "name" not in cols:
                await db.execute("ALTER TABLE replica_templates ADD COLUMN name TEXT")
        except Exception:
            # 不因兼容迁移失败而阻断启动
            pass
        # 兼容旧库：clips 补齐 created_at / updated_at
        try:
            cur = await db.execute("PRAGMA table_info(clips)")
            cols = [str(r[1]) for r in await cur.fetchall()]  # (cid, name, type, notnull, dflt_value, pk)
            if "created_at" not in cols:
                # SQLite 旧表 ADD COLUMN 时对非常量默认值限制较多，先加普通列再回填
                await db.execute("ALTER TABLE clips ADD COLUMN created_at TEXT")
            if "updated_at" not in cols:
                await db.execute("ALTER TABLE clips ADD COLUMN updated_at TEXT")
            await db.execute(
                "UPDATE clips SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP), "
                "updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)"
            )
            # 统一重建触发器：兼容旧库历史触发器定义，避免引用不存在字段
            await db.execute("DROP TRIGGER IF EXISTS trg_clips_updated_at")
            await db.execute("DROP TRIGGER IF EXISTS trg_clips_insert_timestamps")
            await db.execute(
                """
                CREATE TRIGGER trg_clips_insert_timestamps
                AFTER INSERT ON clips
                FOR EACH ROW
                BEGIN
                    UPDATE clips
                    SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
                        updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
                    WHERE id = NEW.id;
                END;
                """
            )
            await db.execute(
                """
                CREATE TRIGGER trg_clips_updated_at
                AFTER UPDATE ON clips
                FOR EACH ROW
                BEGIN
                    UPDATE clips SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
                END;
                """
            )
        except Exception:
            # 不因兼容迁移失败而阻断启动
            pass

        for key, value, type_, label, options in DEFAULT_CONFIG:
            await db.execute(
                "INSERT OR IGNORE INTO config (key, value, type, label, options) VALUES (?,?,?,?,?)",
                (key, value, type_, label, options),
            )

        # 默认总结模板（幂等）
        # 注意：这里使用“模板内占位符”做复用，真正写入库时会在插入前展开
        from datetime import datetime

        now = datetime.now().isoformat(timespec="seconds")
        base_user_prompt = next(t[4] for t in DEFAULT_SUMMARY_TEMPLATES if t[0] == "default_general")
        base_schema_hint = next(t[5] for t in DEFAULT_SUMMARY_TEMPLATES if t[0] == "default_general")

        for tid, name, desc, sys_p, user_p, schema_hint in DEFAULT_SUMMARY_TEMPLATES:
            sys_prompt = (sys_p or "").replace("{{base_user_prompt}}", base_user_prompt).replace("{{base_schema_hint}}", base_schema_hint)
            user_prompt = (user_p or "").replace("{{base_user_prompt}}", base_user_prompt).replace("{{base_schema_hint}}", base_schema_hint)
            out_schema = (schema_hint or "").replace("{{base_schema_hint}}", base_schema_hint)
            await db.execute(
                """
                INSERT OR IGNORE INTO summary_templates
                (id, name, description, system_prompt, user_prompt_template, output_schema_hint, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (tid, name, desc, sys_prompt, user_prompt, out_schema, now, now),
            )
        # 内置「用户自定义风格」占位：实际提示词由 backend/app/api/summary.py 代码注入；满足 video_summaries 外键。
        await db.execute(
            """
            INSERT OR IGNORE INTO summary_templates
            (id, name, description, system_prompt, user_prompt_template, output_schema_hint, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                "user_builtin_note",
                "内置·用户自定义风格",
                "代码内嵌 BASE/MERGE 提示词；总结页已不再选择模板。本条仅满足外键。",
                "（不使用）",
                "（不使用）",
                base_schema_hint,
                now,
                now,
            ),
        )
        # 兼容旧库：补全分割模式可选项与混合模式参数
        await db.execute(
            "UPDATE config SET options = ? WHERE key = 'split_mode'",
            ('["scene","fixed","hybrid"]',),
        )
        await db.execute(
            "UPDATE config SET options = ? WHERE key = 'asr_provider'",
            ('["whisper","openai","bailian"]',),
        )
        await db.execute(
            "UPDATE config SET options = ? WHERE key = 'clip_vcodec'",
            ('["libx264","libx265","h264_nvenc","hevc_nvenc","libvpx-vp9","copy"]',),
        )
        await db.execute(
            "UPDATE config SET options = ? WHERE key = 'export_vcodec'",
            ('["libx264","libx265","h264_nvenc","hevc_nvenc","libvpx-vp9"]',),
        )
        # 兼容旧库：将历史默认 clip_crf=23 升级到 18（用户自定义值不改）
        await db.execute(
            "UPDATE config SET value = '18' WHERE key = 'clip_crf' AND COALESCE(TRIM(value), '') IN ('', '23')",
        )
        # 兼容旧库：将历史绝对路径规范化为相对路径，避免打包后运行目录变化导致找不到文件
        try:
            cur = await db.execute("SELECT id, file_path, thumbnail_path FROM videos")
            rows = await cur.fetchall()
            for r in rows:
                fp = to_stored_path(r[1] or "")
                tp = to_stored_path(r[2] or "") if r[2] else None
                await db.execute(
                    "UPDATE videos SET file_path = ?, thumbnail_path = ? WHERE id = ?",
                    (fp, tp, r[0]),
                )
        except Exception:
            pass
        try:
            cur = await db.execute("SELECT id, clip_path FROM clips")
            rows = await cur.fetchall()
            for r in rows:
                cp = to_stored_path(r[1] or "")
                await db.execute("UPDATE clips SET clip_path = ? WHERE id = ?", (cp, r[0]))
        except Exception:
            pass

        from app.db.run_migrations import run_migrations

        await run_migrations(db)
        await db.commit()
