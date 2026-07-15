import type { ProviderPreset } from './types'

export const VLM_PROVIDERS: ProviderPreset[] = [
  { id: 'openai',      name: 'OpenAI',         logo: '🟢', baseUrl: 'https://api.openai.com/v1',            defaultModel: 'gpt-4o' },
  { id: 'deepseek',    name: 'DeepSeek',        logo: '🔵', baseUrl: 'https://api.deepseek.com/v1',          defaultModel: 'deepseek-chat' },
  { id: 'iflowai',    name: 'iFlow AI',         logo: '🟣', baseUrl: 'https://apis.iflow.cn/v1',             defaultModel: '' },
  { id: 'siliconflow', name: 'SiliconFlow',     logo: '🟠', baseUrl: 'https://api.siliconflow.cn/v1',       defaultModel: 'Qwen/Qwen2-VL-72B-Instruct' },
  { id: 'zhipuai',    name: '智谱 AI',          logo: '🔴', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', defaultModel: 'glm-4v' },
  { id: 'moonshot',   name: 'Moonshot (Kimi)',  logo: '🌙', baseUrl: 'https://api.moonshot.cn/v1',          defaultModel: 'moonshot-v1-8k' },
  { id: 'custom',     name: '自定义',           logo: '⚙️', baseUrl: '' },
]

export const LLM_PROVIDERS: ProviderPreset[] = [
  { id: 'openai',      name: 'OpenAI',         logo: '🟢', baseUrl: 'https://api.openai.com/v1',      defaultModel: 'gpt-4o-mini' },
  { id: 'deepseek',    name: 'DeepSeek',        logo: '🔵', baseUrl: 'https://api.deepseek.com/v1',    defaultModel: 'deepseek-chat' },
  { id: 'iflowai',    name: 'iFlow AI',         logo: '🟣', baseUrl: 'https://apis.iflow.cn/v1',       defaultModel: '' },
  { id: 'siliconflow', name: 'SiliconFlow',     logo: '🟠', baseUrl: 'https://api.siliconflow.cn/v1', defaultModel: 'Qwen/Qwen2.5-72B-Instruct' },
  { id: 'moonshot',   name: 'Moonshot (Kimi)',  logo: '🌙', baseUrl: 'https://api.moonshot.cn/v1',    defaultModel: 'moonshot-v1-8k' },
  { id: 'custom',     name: '自定义',           logo: '⚙️', baseUrl: '' },
]

export const EMBEDDING_PROVIDERS: ProviderPreset[] = [
  { id: 'openai',      name: 'OpenAI',      logo: '🟢', baseUrl: 'https://api.openai.com/v1',      defaultModel: 'text-embedding-3-small' },
  { id: 'siliconflow', name: 'SiliconFlow', logo: '🟠', baseUrl: 'https://api.siliconflow.cn/v1', defaultModel: 'BAAI/bge-m3' },
  { id: 'deepseek',    name: 'DeepSeek',    logo: '🔵', baseUrl: 'https://api.deepseek.com/v1',   defaultModel: '' },
  {
    id: 'volcengine',
    name: '火山引擎（方舟）',
    logo: '🌋',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal',
    defaultModel: 'doubao-embedding-vision-251215',
  },
  { id: 'custom',      name: '自定义',      logo: '⚙️', baseUrl: '' },
]

export const TTS_PROVIDERS: ProviderPreset[] = [
  { id: 'edge-tts',    name: 'Edge TTS',      logo: '🔷', baseUrl: '',                                       defaultModel: '' },
  { id: 'openai',      name: 'OpenAI TTS',    logo: '🟢', baseUrl: 'https://api.openai.com/v1',             defaultModel: 'tts-1' },
  // { id: 'bailian',     name: '百炼 (阿里云)', logo: '🟡', baseUrl: 'https://dashscope.aliyuncs.com/api/v1', defaultModel: 'cosyvoice-v1' },
  // { id: 'volcengine',  name: '火山引擎',      logo: '🌋', baseUrl: 'https://openspeech.bytedance.com',      defaultModel: '' },
  // { id: 'gpt-sovits',  name: 'GPT-SoVITS',   logo: '🎙️', baseUrl: 'http://127.0.0.1:9880',                defaultModel: '' },
  // { id: 'index-tts',   name: 'IndexTTS',      logo: '🎵', baseUrl: 'http://127.0.0.1:7860',                defaultModel: '' },
  { id: 'custom-http', name: '自定义 HTTP',   logo: '⚙️', baseUrl: '',                                       defaultModel: '' },
]

export const ASR_PROVIDERS: ProviderPreset[] = [
  { id: 'whisper',  name: '本地 Whisper', logo: '🎙️', baseUrl: '' },
  { id: 'openai',   name: 'OpenAI / 兼容',  logo: '🟢', baseUrl: 'https://api.openai.com/v1', defaultModel: 'whisper-1' },
]

export const VLM_KEYS  = ['vlm_base_url', 'vlm_api_key', 'vlm_model', 'vlm_provider', 'vlm_context_length', 'vlm_max_images_per_batch', 'vlm_concurrency']
export const LLM_KEYS  = ['llm_base_url', 'llm_api_key', 'llm_model', 'llm_temperature', 'llm_max_tokens', 'llm_max_context_tokens', 'llm_concurrency']
export const EMB_KEYS  = ['embedding_provider', 'embedding_base_url', 'embedding_model', 'embedding_api_key', 'embedding_concurrency', 'vector_dimension', 'top_k', 'match_mode', 'match_top_k', 'match_top_n', 'enrich_enabled', 'match_min_llm_score', 'match_min_similarity']

export const MATCH_MODE_OPTIONS: { value: string; label: string; desc: string }[] = [
  {
    value: 'auto',
    label: '自动',
    desc: '有向量索引时用向量；否则 ASR/VLM 文本 + LLM 精排',
  },
  {
    value: 'vector',
    label: '向量匹配',
    desc: 'Embedding 初筛 + LLM 精排（需配置 Embed）',
  },
  {
    value: 'text',
    label: '文本匹配',
    desc: 'ASR/VLM 文本相似度初筛 + LLM 精排（无需 Embed）',
  },
  {
    value: 'llm_only',
    label: '纯 LLM',
    desc: '直接 LLM 语义评分；素材多时会先文本压候选',
  },
]
export const VIDEO_KEYS = [
  'split_mode',
  'fixed_duration',
  'scene_threshold',
  'scene_min_scene_len',
  'hybrid_max_segment_sec',
  // cut performance (FFmpeg)
  'cut_mode',
  'stream_copy',
  'stream_copy_audio',
  'split_max_workers',
  'ffmpeg_threads_per_job',
  'quiet_split',
  'frame_fps',
  'frame_concurrency',
  'frame_target_pixels',
  // ffmpeg transcode options for clip outputs
  'clip_container',
  'clip_vcodec',
  'clip_acodec',
  'clip_preset',
  'clip_crf',
  'clip_video_bitrate_kbps',
  'clip_audio_bitrate_kbps',
  'clip_g',
  'clip_keyint_min',
  'clip_sc_threshold',
  'clip_fps',
  'clip_scale_width',
  'clip_scale_height',
  'clip_pix_fmt',
  // 成片导出（烧录 / 原声成片）
  'export_container',
  'export_backend',
  'export_gpu',
  'export_vcodec',
  'export_acodec',
  'export_preset',
  'export_crf',
  'export_video_bitrate_kbps',
  'export_audio_bitrate_kbps',
  'export_g',
  'export_keyint_min',
  'export_sc_threshold',
  'export_fps',
  'export_scale_width',
  'export_scale_height',
  'export_pix_fmt',
  'jianying_draft_parent_dir',
]

/** 文案素材成片：Pexels / Pixabay / Unsplash */
export const STOCK_MEDIA_KEYS = [
  'pexels_api_key',
  'pixabay_api_key',
  'unsplash_access_key',
  'stock_media_http_proxy',
]
export const ASR_LANGUAGE_PRESETS: { value: string; label: string }[] = [
  { value: '', label: '自动检测（留空）' },
  { value: 'zh', label: '中文 (zh)' },
  { value: 'en', label: '英文 (en)' },
  { value: 'ja', label: '日文 (ja)' },
  { value: 'ko', label: '韩文 (ko)' },
  { value: 'yue', label: '粤语 (yue)' },
  { value: 'fr', label: '法文 (fr)' },
  { value: 'de', label: '德文 (de)' },
  { value: 'es', label: '西班牙文 (es)' },
  { value: 'ru', label: '俄文 (ru)' },
  { value: 'pt', label: '葡萄牙文 (pt)' },
]

export const ASR_KEYS = [
  'asr_provider',
  'asr_model',
  'asr_base_url',
  'asr_api_key',
  'asr_openai_model',
  'asr_language',
  'asr_concurrency',
  'asr_auto_correct',
  'asr_auto_correct_apply',
]
export const TTS_KEYS  = [
  'tts_provider',
  // edge-tts
  'tts_voice', 'tts_rate', 'tts_volume',
  // openai / bailian (openai-compatible)
  'tts_base_url', 'tts_api_key', 'tts_model', 'tts_format',
  // concurrency
  'tts_concurrency',
  // bailian
  'bailian_app_key',
  // volcengine
  'volcengine_app_id', 'volcengine_token', 'volcengine_cluster',
  // gpt-sovits
  'gsv_ref_audio', 'gsv_ref_text', 'gsv_lang',
  // index-tts
  'index_tts_ref_audio',
  // custom-http
  'custom_tts_method', 'custom_tts_url', 'custom_tts_headers', 'custom_tts_body',
  'custom_tts_response_type', 'custom_tts_audio_key',
]
