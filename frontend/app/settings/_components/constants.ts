import type { ProviderPreset } from './types'

export const VLM_PROVIDERS: ProviderPreset[] = [
  { id: 'openai',      name: 'OpenAI',         logo: '🟢', baseUrl: 'https://api.openai.com/v1',            defaultModel: 'gpt-4o' },
  { id: 'deepseek',    name: 'DeepSeek',        logo: '🔵', baseUrl: 'https://api.deepseek.com/v1',          defaultModel: 'deepseek-chat' },
  { id: 'iflowai',    name: 'iFlow AI',         logo: '🟣', baseUrl: 'https://api.iflow.ai/v1',             defaultModel: '' },
  { id: 'siliconflow', name: 'SiliconFlow',     logo: '🟠', baseUrl: 'https://api.siliconflow.cn/v1',       defaultModel: 'Qwen/Qwen2-VL-72B-Instruct' },
  { id: 'zhipuai',    name: '智谱 AI',          logo: '🔴', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', defaultModel: 'glm-4v' },
  { id: 'moonshot',   name: 'Moonshot (Kimi)',  logo: '🌙', baseUrl: 'https://api.moonshot.cn/v1',          defaultModel: 'moonshot-v1-8k' },
  { id: 'custom',     name: '自定义',           logo: '⚙️', baseUrl: '' },
]

export const EMBEDDING_PROVIDERS: ProviderPreset[] = [
  { id: 'openai',      name: 'OpenAI',      logo: '🟢', baseUrl: 'https://api.openai.com/v1',      defaultModel: 'text-embedding-3-small' },
  { id: 'siliconflow', name: 'SiliconFlow', logo: '🟠', baseUrl: 'https://api.siliconflow.cn/v1', defaultModel: 'BAAI/bge-m3' },
  { id: 'deepseek',    name: 'DeepSeek',    logo: '🔵', baseUrl: 'https://api.deepseek.com/v1',   defaultModel: '' },
  { id: 'custom',      name: '自定义',      logo: '⚙️', baseUrl: '' },
]

export const VLM_KEYS  = ['vlm_base_url', 'vlm_api_key', 'vlm_model', 'vlm_provider', 'llm_model']
export const EMB_KEYS  = ['embedding_provider', 'embedding_base_url', 'embedding_model', 'embedding_api_key', 'vector_dimension', 'top_k', 'match_top_k', 'match_top_n']
export const VIDEO_KEYS = ['split_mode', 'fixed_duration', 'scene_threshold', 'frame_fps', 'asr_model']
export const TTS_KEYS  = ['tts_provider', 'tts_voice', 'tts_rate', 'tts_volume']
