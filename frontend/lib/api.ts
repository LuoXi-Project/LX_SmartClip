import axios, { AxiosHeaders, type AxiosRequestHeaders } from 'axios'

import { API_BASE_URL } from './runtime-config'

export { API_BASE_URL }

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

export interface LicenseStatus {
  enforced: boolean
  /** 后端是否存在可连的卡密服务器配置（config.json） */
  has_server_config: boolean
  has_stored_card: boolean
  valid: boolean
}

export const licenseApi = {
  status: () => apiClient.get<unknown, LicenseStatus>('/api/license/status'),
  activate: (card: string) =>
    apiClient.post<unknown, { ok: boolean; message: string }>('/api/license/activate', { card }),
  unbind: (card: string) =>
    apiClient.post<unknown, { ok: boolean; message: string }>('/api/license/unbind', { card }),
}

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

const WS_BASE_URL = typeof window !== 'undefined'
  ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
  : 'ws://localhost:8000'

export function createProcessWebSocket(
  videoId: string,
  skipSteps: string[] = []
): WebSocket {
  const ws = new WebSocket(`${WS_BASE_URL}/api/videos/${videoId}/process-ws`)
  ws.addEventListener('open', () => {
    // 后端会等待首条 JSON（包含 skip_steps）后再进入处理流程。
    // 即便为空数组，也必须主动发送，避免“开始后无响应，断开后才开始”。
    ws.send(JSON.stringify({ skip_steps: skipSteps }))
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

// 语义素材检索
export interface SemanticSearchFilters {
  video_ids?: string[]
}

export interface SemanticSearchRequest {
  query: string
  top_k?: number
  top_n?: number
  highlight_only?: boolean
  filters?: SemanticSearchFilters
}

export interface SemanticSearchSegment {
  clip_id: string
  start_time: number
  end_time: number
  duration: number
  score: number
  summary_text?: string | null
  is_highlight: boolean
  highlight_score: number
  thumbnail_url?: string | null
  preview_url?: string | null
}

export interface SemanticSearchAssetResult {
  asset_id: string
  asset_title: string
  duration?: number | null
  cover_url?: string | null
  asset_score: number
  segments: SemanticSearchSegment[]
}

export interface SemanticSearchResponse {
  query: string
  results: SemanticSearchAssetResult[]
}

export const searchApi = {
  semanticSearch: (payload: SemanticSearchRequest) =>
    apiClient.post<unknown, SemanticSearchResponse>('/api/search/assets/semantic', payload),
  browseHighlights: (payload: HighlightBrowseRequest) =>
    apiClient.post<unknown, HighlightBrowseResponse>('/api/search/highlights', payload),
}

// 高光浏览（无需检索）
export interface HighlightBrowseFilters {
  video_ids?: string[]
}

export interface HighlightBrowseRequest {
  limit_assets?: number
  limit_segments_per_asset?: number
  min_score?: number
  filters?: HighlightBrowseFilters
}

export interface HighlightBrowseSegment {
  clip_id: string
  start_time: number
  end_time: number
  duration: number
  highlight_score: number
  summary_text?: string | null
}

export interface HighlightBrowseAssetResult {
  asset_id: string
  asset_title: string
  duration?: number | null
  cover_url?: string | null
  asset_score: number
  segments: HighlightBrowseSegment[]
}

export interface HighlightBrowseResponse {
  results: HighlightBrowseAssetResult[]
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
  importByUrl: (payload: { url: string; title?: string }) =>
    apiClient.post<unknown, Video>('/api/videos/import-url', payload),
  delete: (id: string) => apiClient.delete(`/api/videos/${id}`),
  rename: (id: string, name: string) => apiClient.patch<unknown, { id: string; name: string }>(`/api/videos/${id}`, { name }),
  process: (id: string) => apiClient.post(`/api/videos/${id}/process`),
  processCancel: (id: string) =>
    apiClient.post<unknown, { ok: boolean; video_id: string }>(`/api/videos/${id}/process-cancel`),
  highlights: (id: string, params?: { limit?: number; min_score?: number }) =>
    apiClient.get<unknown, { video_id: string; total: number; segments: Array<{
      clip_id: string
      start_time: number
      end_time: number
      duration: number
      highlight_score: number
      summary_text?: string | null
    }> }>(`/api/videos/${id}/highlights`, { params }),
}

export const matchApi = {
  run: (payload: MatchRequest) => apiClient.post<unknown, MatchResponse>('/api/match', payload),
}

/** ASR 时间轴片段 JSON（存库为字符串，解析后为 list） */
export type AsrSegmentJson = { start: number; end: number; text: string }

export interface ClipResult {
  id: string
  clip_path: string
  start_time: number
  end_time: number
  duration: number
  asr_text: string | null
  /** JSON 字符串：AsrSegmentJson[]，时间相对片段内音频 */
  asr_segments: string | null
  vlm_description: string | null
}

export const clipsApi = {
  listByVideo: (videoId: string) =>
    apiClient.get<unknown, ClipResult[]>(`/api/videos/${videoId}/clips`),
  update: (
    clipId: string,
    payload: { asr_text?: string | null; asr_segments?: string | null; vlm_description?: string | null },
  ) =>
    apiClient.patch<unknown, { ok: boolean; clip_id: string }>(`/api/videos/clips/${clipId}`, payload),
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

export interface ReplicaIngestResponse {
  video_id: string
  name: string
  status: string
}

export interface ReplicaTemplateDraftResponse {
  template_id: string
  template_json: any
  template_guide: string
  status: 'draft'
}

export interface ReplicaTemplateConfirmedResponse {
  template_id: string
  template_json: any
  template_guide: string
  status: 'confirmed'
}

export interface ReplicaTemplateListItem {
  template_id: string
  name: string | null
  source_video_id: string
  source_url: string | null
  pace: string | null
  tone: string | null
  status: 'draft' | 'confirmed'
  created_at: string
  updated_at: string
  guide_preview: string
}

export interface ReplicaTemplateListResponse {
  items: ReplicaTemplateListItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export const replicaApi = {
  ingest: (payload: { url: string; title?: string; download_mode?: 'best'; max_download_duration_sec?: number }) =>
    apiClient.post<unknown, ReplicaIngestResponse>('/api/replica/ingest', payload),

  generateTemplate: (videoId: string, payload?: { skip_vlm?: boolean; max_clips?: number }) =>
    apiClient.post<unknown, ReplicaTemplateDraftResponse>(`/api/replica/${videoId}/generate-template`, payload ?? {}),

  confirmTemplate: (templateId: string, payload: { name?: string; template_guide: string; template_json?: any }) =>
    apiClient.post<unknown, ReplicaTemplateConfirmedResponse>(`/api/replica/template/${templateId}/confirm`, payload),

  getTemplate: (templateId: string) =>
    apiClient.get<unknown, any>(`/api/replica/template/${templateId}`),

  listTemplates: (params?: { q?: string; status?: 'draft' | 'confirmed'; sort?: 'updated_desc' | 'created_desc'; page?: number; page_size?: number }) =>
    apiClient.get<unknown, ReplicaTemplateListResponse>('/api/replica/templates', { params }),

  deleteTemplate: (templateId: string) =>
    apiClient.delete<unknown, { ok: boolean; template_id: string }>(`/api/replica/template/${templateId}`),

  renameTemplate: (templateId: string, name: string) =>
    apiClient.patch<unknown, { ok: boolean; template_id: string; name: string }>(`/api/replica/template/${templateId}`, { name }),
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

// 自动一键成片 · Plan
export type AutoEditMode = 'auto' | 'voiceover' | 'original'

export interface PlanKeepFlagsApi {
  clips?: boolean
  subtitles?: boolean
  transitions?: boolean
  bgm?: boolean
}

export interface AutoEditPlanRequestApi {
  video_ids: string[]
  user_prompt: string
  mode?: AutoEditMode
  /** 模板剪辑预设：仅在 match 页 mode=template 时使用 */
  template_preset?: string
  target_duration_sec?: number
  num_plans?: number
  allow_cross_video?: boolean
  subtitle_policy?: 'auto' | 'asr' | 'rewrite' | 'none'
  transition_policy?: 'auto' | 'hard_cut' | 'soft'
  bgm_policy?: 'auto' | 'none' | 'user' | 'ai'
  plan_keep_flags?: PlanKeepFlagsApi
  prev_plan_id?: string | null
  prev_plan?: unknown
  /** 低侵入升级：启用事件级时间轴引擎 */
  use_timeline_engine?: boolean
  /** 调试：生成可解释中间产物（后端可能仅用于日志/落盘） */
  explain?: boolean
}

export interface AutoEditSegmentPlanApi {
  id: string
  chapter_id?: string | null
  order: number
  clip_group?: Array<{
    clip_id: string
    video_id: string
    weight?: number
  }>
  selected_clip_ids?: string[]
  start_time_sec: number
  end_time_sec: number
  /** 用户手动覆盖该段在成片中的时长（秒）。用于“更可控”的段落时长/字幕节奏。 */
  override_duration_sec?: number | null
  audio_mode: 'original' | 'tts' | 'mute'
  subtitle?: {
    strategy: 'auto' | 'asr' | 'rewrite' | 'none'
    text: string
    source: 'asr' | 'llm' | 'user'
  }
}

export interface AutoEditBgmPlanApi {
  enabled: boolean
  source?: 'library' | 'user' | 'ai'
  track_id?: string | null
  volume_db?: number
  loop?: boolean
  fade_in_sec?: number
  fade_out_sec?: number
}

export interface AutoEditPlanApi {
  plan_id: string
  title: string
  summary: string
  /** Timeline Engine 方案补充的“素材视频元信息”（兼容字段） */
  video_title?: string | null
  video_description?: string | null
  mode: AutoEditMode
  target_duration_sec?: number | null
  estimated_duration_sec?: number | null
  segments: AutoEditSegmentPlanApi[]
  bgm?: AutoEditBgmPlanApi | null
}

export interface AutoEditPlanResponseApi {
  plans: AutoEditPlanApi[]
}

export interface AutoEditPlanSessionResponseApi {
  session_id: string
  stream_url: string
}

export type VoiceoverQuickCutStrategyApi = 'asr_fast' | 'standard' | 'semantic'

export interface VoiceoverQuickCutRequestApi {
  video_ids: string[]
  strategy: VoiceoverQuickCutStrategyApi
  user_prompt?: string
}

export const autoEditApi = {
  templates: () =>
    apiClient.get<unknown, Array<{ id: string; label: string }>>('/api/auto-edit/templates'),
  plan: (payload: AutoEditPlanRequestApi) =>
    apiClient.post<unknown, AutoEditPlanResponseApi>('/api/auto-edit/plan', payload),
  createPlanSession: (payload: AutoEditPlanRequestApi) =>
    apiClient.post<unknown, AutoEditPlanSessionResponseApi>('/api/auto-edit/plan/session', payload),
  voiceoverQuickCut: (payload: VoiceoverQuickCutRequestApi) =>
    apiClient.post<unknown, AutoEditPlanResponseApi>('/api/auto-edit/voiceover-quick-cut', payload),
  realize: (payload: { plan: AutoEditPlanApi; project_name?: string; include_subtitle?: boolean; style?: import('./subtitle-types').SubtitleStyle }) =>
    apiClient.post<unknown, { mode: 'voiceover' | 'original'; filename: string; url: string }>('/api/auto-edit/realize', payload),
}

// BGM 音乐库管理
export interface BgmTrack {
  id: string
  title: string
  mood?: string | null
  bpm?: number | null
  tags: string[]
  filename: string
  url: string
}

export interface BgmUpdatePayload {
  title?: string
  mood?: string | null
  bpm?: number | null
  tags?: string[]
}

/** FormData 上传：去掉默认的 application/json/手写 multipart，由浏览器自动带 boundary，否则服务端常拿不到原始 filename。 */
function formDataPostConfig() {
  return {
    transformRequest: [
      (data: unknown, headers: AxiosRequestHeaders) => {
        if (data instanceof FormData) {
          if (headers instanceof AxiosHeaders) {
            headers.delete('Content-Type')
          } else if (headers && typeof headers === 'object' && !Array.isArray(headers)) {
            delete (headers as Record<string, unknown>)['Content-Type']
          }
        }
        return data
      },
    ],
  }
}

export const bgmApi = {
  list: () => apiClient.get<unknown, BgmTrack[]>('/api/bgm/tracks'),
  upload: (file: File, meta?: { title?: string; mood?: string; bpm?: number; tags?: string[] }) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('client_filename', file.name || '')
    if (meta?.title) formData.append('title', meta.title)
    if (meta?.mood) formData.append('mood', meta.mood)
    if (typeof meta?.bpm === 'number') formData.append('bpm', String(meta.bpm))
    if (meta?.tags?.length) formData.append('tags', meta.tags.join(','))
    return apiClient.post<unknown, BgmTrack>('/api/bgm/upload', formData, formDataPostConfig())
  },
  update: (id: string, payload: BgmUpdatePayload) =>
    apiClient.patch<unknown, BgmTrack>(`/api/bgm/tracks/${id}`, payload),
  delete: (id: string) => apiClient.delete(`/api/bgm/tracks/${id}`),
}
