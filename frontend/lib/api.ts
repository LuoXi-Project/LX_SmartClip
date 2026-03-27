import axios from 'axios'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

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
  process: (id: string) => apiClient.post(`/api/videos/${id}/process`),
}

export const matchApi = {
  run: (payload: MatchRequest) => apiClient.post<unknown, MatchResponse>('/api/match', payload),
}

export const exportApi = {
  downloadProject: (payload: ExportRequest) =>
    apiClient.post('/api/export/project', payload, { responseType: 'blob' }),
  downloadMerged: (payload: MergeRequest) =>
    apiClient.post('/api/export/merged', payload, { responseType: 'blob' }),
}

export interface ExportRequest {
  clip_ids: string[]
  project_name?: string
  include_audio?: boolean
  tts_filenames?: string[]
}

export interface MergedSegment {
  clip_id: string
  tts_filename?: string
  copy_text?: string
}

export interface MergeRequest {
  segments: MergedSegment[]
  project_name?: string
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
