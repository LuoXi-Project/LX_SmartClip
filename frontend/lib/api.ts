import axios from 'axios'

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export default apiClient

const WS_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000')
  .replace(/^http/, 'ws')

export function createProcessWebSocket(
  videoId: string,
  skipSteps: string[] = []
): WebSocket {
  const ws = new WebSocket(`${WS_BASE_URL}/api/videos/${videoId}/process-ws`)
  ws.addEventListener('open', () => {
    if (skipSteps.length > 0) {
      ws.send(JSON.stringify({ skip_steps: skipSteps }))
    }
  })
  return ws
}

export interface VideoListParams {
  q?: string
  status?: string
  sort?: string
  page?: number
  page_size?: number
}

export interface VideoListResponse {
  items: Video[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export const videosApi = {
  list: (params?: VideoListParams) =>
    apiClient.get<unknown, VideoListResponse>('/api/videos', { params }),
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post<unknown, Video>('/api/videos/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  delete: (id: string) => apiClient.delete(`/api/videos/${id}`),
  rename: (id: string, name: string) => apiClient.patch<unknown, { id: string; name: string }>(`/api/videos/${id}`, { name }),
  process: (id: string) => apiClient.post(`/api/videos/${id}/process`),
}

export const matchApi = {
  run: (payload: MatchRequest) => apiClient.post<unknown, MatchResponse>('/api/match', payload),
}

export const exportApi = {
  downloadProject: (payload: ExportRequest) =>
    apiClient.post('/api/export/project', payload, { responseType: 'blob' }),
}

export interface ExportRequest {
  clip_ids: string[]
  project_name?: string
  include_audio?: boolean
  tts_filenames?: string[]
}


export interface CopyGenRequest {
  video_ids: string[]
  user_prompt: string
  style?: string
  max_segments?: number
  stream?: boolean
}

export interface SubtitleStyleApi {
  font_name?: string
  font_size?: number
  font_color?: string
  outline_color?: string
  outline_width?: number
  shadow?: number
  bold?: boolean
  italic?: boolean
  position?: string
  margin_v?: number
  pos_x_pct?: number
  pos_y_pct?: number
  background?: boolean
  max_chars_per_line?: number
}

export interface SubtitleSegmentInput {
  copy_text: string
  clip_id: string
  clip_ids?: string[]
  tts_filename?: string
}

export interface GenerateSRTRequest {
  segments: SubtitleSegmentInput[]
  style?: SubtitleStyleApi
  use_tts_timing?: boolean
}

export interface SRTEntryApi {
  index: number
  start: number
  end: number
  text: string
  clip_id: string
}

export interface GenerateSRTResponse {
  srt_content: string
  entries: SRTEntryApi[]
  total_duration: number
  timing_source: string
}

export interface BurnSubtitleRequest {
  segments: SubtitleSegmentInput[]
  srt_content: string
  style?: SubtitleStyleApi
  project_name?: string
}

export interface BurnSubtitleResponse {
  filename: string
  url: string
}

export interface ExportOriginalRequest {
  segments: SubtitleSegmentInput[]
  style?: SubtitleStyleApi
  project_name?: string
  include_subtitle?: boolean
  normalize_audio?: boolean
}

export const subtitleApi = {
  generate: (payload: GenerateSRTRequest) =>
    apiClient.post<unknown, GenerateSRTResponse>('/api/subtitle/generate', payload),
  burn: (payload: BurnSubtitleRequest) =>
    apiClient.post<unknown, BurnSubtitleResponse>('/api/subtitle/burn', payload),
  exportOriginal: (payload: ExportOriginalRequest) =>
    apiClient.post<unknown, BurnSubtitleResponse>('/api/subtitle/export_original', payload),
}

export const copyGenApi = {
  /** Stream SSE — returns raw Response for caller to consume */
  generateStream: (payload: CopyGenRequest): Promise<Response> =>
    fetch(`${API_BASE_URL}/api/copy-gen/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...payload, stream: true }),
    }),
}

export const ttsApi = {
  synthesize: (payload: TTSRequest) => apiClient.post<unknown, TTSResponse>('/api/tts/synthesize', payload),
  listVoices: (locale?: string) => apiClient.get<unknown, VoiceInfo[]>(`/api/tts/voices${locale ? `?locale=${locale}` : ''}`),
  audioUrl: (filename: string) => `${API_BASE_URL}/api/tts/audio/${filename}`,
}

export interface Video {
  id: string
  name: string
  file_path: string
  thumbnail_path: string | null
  duration: number | null
  total_clips: number
  split_mode: string
  status: 'pending' | 'processing' | 'done' | 'error'
  upload_at: string
}

export interface ProcessMessage {
  step: 'split' | 'extract_frames' | 'asr' | 'vlm' | 'embed' | 'done' | 'error'
  status: 'running' | 'done' | 'error' | 'skip'
  message: string
  detail: Record<string, unknown>
}

export interface MatchRequest {
  query: string
  top_k?: number
  top_n?: number
  video_ids?: string[] | null
}

export interface MatchClip {
  clip_id: string
  video_id: string
  clip_path: string
  start_time: number
  end_time: number
  duration: number
  asr_text: string | null
  vlm_description: string | null
  thumbnail_url: string | null
  preview_url: string | null
  score: number
  reason: string
}

export interface TTSRequest {
  text: string
  voice?: string
  rate?: string
  volume?: string
}

export interface TTSResponse {
  filename: string
  url: string
  voice: string
  rate: string
  volume: string
  text_length: number
}

export interface VoiceInfo {
  name: string
  locale: string
  gender: string
  friendly_name: string
}

export interface MatchResponse {
  query: string
  top_n: number
  recommended: MatchClip[]
  candidates: MatchClip[]
}
