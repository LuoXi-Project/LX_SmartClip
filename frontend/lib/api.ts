import axios, { AxiosHeaders, type AxiosRequestHeaders } from 'axios'

import { API_BASE_URL } from './runtime-config'
import type { SubtitleStyle } from './subtitle-types'

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

/**
 * 将 axios/FastAPI 错误解析为可读文案（支持 detail 为 string、校验错误数组或结构化对象）。
 */
export function formatFastApiDetail(error: unknown): string {
  const ax = error as {
    response?: { data?: { detail?: unknown } }
    message?: string
  }
  const detail = ax.response?.data?.detail
  if (detail === undefined || detail === null || detail === '') {
    return ax.message || '请求失败'
  }
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item: unknown) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          const loc = (item as { loc?: unknown[] }).loc
          const msg = (item as { msg?: unknown }).msg
          const locStr = Array.isArray(loc) ? loc.filter(Boolean).join('.') : ''
          return locStr ? `${locStr}: ${String(msg)}` : String(msg)
        }
        return JSON.stringify(item)
      })
      .join('; ')
  }
  if (typeof detail === 'object') {
    const o = detail as {
      message?: string
      invalid_clip_ids?: string[]
      tts_failures?: Array<{ segment_id?: string; error?: string }>
    }
    const parts: string[] = []
    if (o.message) parts.push(o.message)
    if (o.invalid_clip_ids?.length) {
      parts.push(`无效 clip_id: ${o.invalid_clip_ids.join(', ')}`)
    }
    if (o.tts_failures?.length) {
      parts.push(o.tts_failures.map((f) => `[${f.segment_id ?? '段落'}] ${f.error ?? ''}`).join('\n'))
    }
    if (parts.length) return parts.join('\n')
    try {
      return JSON.stringify(detail)
    } catch {
      return String(detail)
    }
  }
  return String(detail)
}

const WS_BASE_URL = typeof window !== 'undefined'
  ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
  : 'ws://localhost:8000'

export interface ProcessJobCreateBody {
  skip_steps?: string[]
  clip_ids?: string[] | null
  /** 增量多向量化：仅补齐缺失子空间向量（供「继续拆维度向量化」使用） */
  embed_incremental?: boolean
}

export function createProcessWebSocket(
  videoId: string,
  skipSteps: string[] = [],
  clipIds?: string[] | null,
  embedIncremental?: boolean,
): WebSocket {
  const ws = new WebSocket(`${WS_BASE_URL}/api/videos/${videoId}/process-ws`)
  ws.addEventListener('open', () => {
    // 后端会等待首条 JSON（包含 skip_steps / optionally clip_ids）后再进入处理流程。
    const payload: ProcessJobCreateBody = { skip_steps: skipSteps }
    if (clipIds != null && clipIds.length > 0) payload.clip_ids = clipIds
    if (embedIncremental) payload.embed_incremental = true
    ws.send(JSON.stringify(payload))
  })
  return ws
}

export interface ProcessTaskSnapshot {
  id: string
  video_id: string
  status: 'pending' | 'running' | 'done' | 'error' | 'cancelled'
  current_step: string | null
  steps: Record<string, { status: string; message: string; detail: Record<string, unknown> }>
  metrics: Record<string, unknown> | null
  error_message: string | null
  created_at: string
  updated_at: string
  finished_at: string | null
}

export function connectProcessJobWebSocket(taskId: string): WebSocket {
  return new WebSocket(`${WS_BASE_URL}/api/process-jobs/${taskId}/ws`)
}

export const processJobsApi = {
  create: (videoId: string, body?: ProcessJobCreateBody) =>
    apiClient.post<
      unknown,
      {
        task_id: string
        video_id: string
        video_name?: string
        job_id: string
        status: string
        queue_size?: number
        queue_position?: number
        stream_url: string
        job_stream_url?: string
      }
    >(`/api/videos/${videoId}/process-jobs`, body ?? {}),
  get: (taskId: string) =>
    apiClient.get<unknown, ProcessTaskSnapshot>(`/api/process-jobs/${taskId}`),
  cancel: (taskId: string) =>
    apiClient.post<unknown, { ok: boolean; task_id: string; video_id: string }>(`/api/process-jobs/${taskId}/cancel`),
}

// ── 通用后台任务（async_jobs）────────────────────────────────────────────────
export interface JobSnapshot {
  id: string
  kind: string
  ref_type: string | null
  ref_id: string | null
  video_name?: string | null
  status: 'pending' | 'running' | 'done' | 'error' | 'cancelled'
  current_step: string | null
  steps: Record<string, { status: string; message: string; detail: Record<string, unknown> }>
  metrics: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error_message: string | null
  /** 活跃任务列表中的排队顺序（0=正在跑）*/
  queue_index?: number
  created_at: string
  updated_at: string
  finished_at: string | null
}

export interface JobListResponse {
  items: JobSnapshot[]
  total: number
}

export const jobsApi = {
  get: (jobId: string) =>
    apiClient.get<unknown, JobSnapshot>(`/api/jobs/${jobId}`),
  list: (params?: { kind?: string; active?: boolean; ref_id?: string; limit?: number }) =>
    apiClient.get<unknown, JobListResponse>('/api/jobs', { params }),
  cancel: (jobId: string) =>
    apiClient.post<unknown, { ok: boolean; job_id: string }>(`/api/jobs/${jobId}/cancel`),
  remove: (jobId: string) =>
    apiClient.delete<unknown, { ok: boolean; job_id: string; deleted: boolean }>(`/api/jobs/${jobId}`),
  streamUrl: (jobId: string) => `/api/jobs/${jobId}/stream`,
}

export interface VideoListParams {
  q?: string
  status?: string
  /** 排除某状态（如 error），与 status 互斥；服务端分页计数与列表一致 */
  exclude_status?: string
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
  match_mode?: MatchMode
  /** LLM 精排控制：true=强制启用；false=跳过；不传=默认行为 */
  refine?: boolean
  /** 向量检索限定的子空间（仅 vector 模式生效）；不传=自动选择所有有数据的子空间 */
  subspaces?: Subspace[]
  filters?: SemanticSearchFilters
}

/** 向量子空间：asr=台词 / vlm=画面 / abstract=抽象主题 / legacy=混合 */
export type Subspace = 'asr' | 'vlm' | 'abstract' | 'legacy'

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

/**
 * 片段原文件下载地址（GET /api/videos/clips/{clip_id}/download）。
 * 与 stream 同源，但强制 attachment，浏览器走下载。
 */
export function clipDownloadUrl(clipId: string): string {
  return `${API_BASE_URL}/api/videos/clips/${clipId}/download`
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
  importByUrl: (payload: {
    url: string
    title?: string
    resolution?: 'best' | '1080p' | '720p' | '480p' | '360p'
    fps_limit?: number
    prefer_mp4?: boolean
  }) =>
    apiClient.post<unknown, Video>('/api/videos/import-url', payload),
  reencode: (id: string, payload: {
    vcodec: 'libx264' | 'libx265'
    crf: number
    preset: 'ultrafast' | 'superfast' | 'veryfast' | 'faster' | 'fast' | 'medium' | 'slow'
    fps?: number
    max_height?: number
    acodec: 'aac'
    audio_bitrate_k: number
  }) => apiClient.post<unknown, { job_id: string; status: string; stream_url: string; ws_url: string; video_id: string }>(`/api/videos/${id}/reencode`, payload),
  delete: (id: string) => apiClient.delete(`/api/videos/${id}`),
  rename: (id: string, name: string) => apiClient.patch<unknown, { id: string; name: string }>(`/api/videos/${id}`, { name }),
  updateStatus: (id: string, status: Video['status']) =>
    apiClient.patch<unknown, { id: string; status: Video['status'] }>(`/api/videos/${id}`, { status }),
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
  /** 智能标注：旁白适配摘要 */
  abstract_summary: string | null
  /** 智能标注：JSON 字符串 string[]，关键词 */
  keywords: string | null
  /** 智能标注：JSON 字符串 string[]，情绪标签 */
  emotion_tags: string | null
}

export const clipsApi = {
  listByVideo: (videoId: string) =>
    apiClient.get<unknown, ClipResult[]>(`/api/videos/${videoId}/clips`),
  update: (
    clipId: string,
    payload: {
      asr_text?: string | null
      asr_segments?: string | null
      vlm_description?: string | null
      abstract_summary?: string | null
      keywords?: string | null
      emotion_tags?: string | null
    },
  ) =>
    apiClient.patch<unknown, { ok: boolean; clip_id: string }>(`/api/videos/clips/${clipId}`, payload),
}

/** ASR 结果 LLM 校准：单片段返回结构 */
export interface AsrCorrectResult {
  clip_id: string
  original_text: string
  corrected_text: string
  original_segments: AsrSegmentJson[]
  corrected_segments: AsrSegmentJson[]
  changed: boolean
  applied: boolean
  vector_stale: boolean
}

/** ASR 结果 LLM 校准：批量单条结果 */
export interface AsrCorrectBatchItem {
  clip_id: string
  status: 'success' | 'error'
  changed?: boolean
  applied?: boolean
  original_text?: string
  corrected_text?: string
  /** 句级原文（success 时有值），供审核层逐句对比 */
  original_segments?: AsrSegmentJson[]
  /** 句级校准后（success 时有值），供审核层逐句对比 */
  corrected_segments?: AsrSegmentJson[]
  error?: string
}

export interface AsrCorrectBatchResult {
  video_id: string
  total: number
  success: number
  changed: number
  applied: boolean
  vector_stale: boolean
  results: AsrCorrectBatchItem[]
}

export const asrApi = {
  /** 校准单个片段 ASR（apply=false 预览，true 直接写库）；hint 可选覆盖全局提示词 */
  correctClip: (clipId: string, apply: boolean, hint?: string) =>
    apiClient.post<unknown, AsrCorrectResult>(
      `/api/videos/clips/${clipId}/asr-correct`,
      { apply, ...(hint !== undefined ? { hint } : {}) },
    ),
  /** 批量校准视频下片段 ASR；hint 可选覆盖全局提示词 */
  correctBatch: (
    videoId: string,
    payload: { clip_ids?: string[]; apply: boolean; hint?: string },
  ) =>
    apiClient.post<unknown, AsrCorrectBatchResult>(
      `/api/videos/${videoId}/asr-correct-batch`,
      payload,
    ),
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
  background_pad_x?: number
  background_pad_y?: number
  background_opacity?: number
  max_chars_per_line?: number
}

export interface SubtitleClipTrimPart {
  clip_id: string
  clip_start_sec?: number
  duration_sec: number
}

export interface SubtitleSegmentInput {
  copy_text: string
  clip_id: string
  clip_ids?: string[]
  tts_filename?: string
  /** 从 clip 文件起点算起的入点（秒），与 duration_sec 联用 */
  clip_start_sec?: number
  /** 使用的片段时长（秒）= 出点 − 入点 */
  duration_sec?: number
  /** 多素材时每条的入点与使用时长，顺序与 clip_ids 一致 */
  clip_trims?: SubtitleClipTrimPart[]
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
  export_backend?: 'ffmpeg' | 'moviepy'
  /** 完全按传入 srt_content 烧录；不做 TTS 对齐兜底重建 */
  strict_use_client_srt?: boolean
  bgm?: BgmMixConfigApi
  /** 默认 true：从原始完整视频裁剪；false：用预处理 clip */
  materialize_from_source?: boolean
  tts_align?: TtsVideoAlignConfigApi | null
  require_tts_audio?: boolean
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
  export_backend?: 'ffmpeg' | 'moviepy'
  bgm?: BgmMixConfigApi
  /** 默认 true：从原始完整视频裁剪；false：用预处理 clip */
  materialize_from_source?: boolean
  /**
   * 画面时长 < 配音时的补足策略。原声导出本身不消费此字段（后端走 render_original_segment），
   * 保留仅为与「一键成片」请求体对称、便于前端统一携带用户所选策略。
   */
  tts_align?: TtsVideoAlignConfigApi | null
}

/** 仅剪映草稿 ZIP，不烧录 MP4 */
export interface JianYingDraftExportRequestApi {
  mode: 'tts' | 'original'
  segments: SubtitleSegmentInput[]
  style?: SubtitleStyleApi
  project_name?: string
  srt_content?: string
  strict_use_client_srt?: boolean
  include_subtitle?: boolean
  tts_align?: TtsVideoAlignConfigApi | null
}

export interface JianYingDraftExportResponseApi {
  mode: 'zip' | 'direct'
  filename: string
  url: string
  local_path: string
}

/** 自动剪辑等待下载用的剪映草稿信息（ZIP 或直写目录） */
export type AutoJianyingDraftDownloadEntryApi =
  | { mode: 'zip'; filename: string; url: string }
  | { mode: 'direct'; local_path: string }

export interface PickFolderResponseApi {
  path: string
  cancelled: boolean
}

/** 本机后端弹出系统文件夹选择（仅 localhost） */
export function pickConfigFolder(): Promise<PickFolderResponseApi> {
  return apiClient.post<unknown, PickFolderResponseApi>('/api/config/pick-folder', {})
}

export interface BgmTimelineSegmentApi {
  start_sec: number
  end_sec: number
  track_id?: string
  volume_db?: number
}

export interface BgmMixConfigApi {
  enabled: boolean
  track_id?: string
  track_ids?: string[]
  track_volumes_db?: Record<string, number>
  volume_db?: number
  loop?: boolean
  fade_in_sec?: number
  fade_out_sec?: number
  timeline_segments?: BgmTimelineSegmentApi[]
}

export const subtitleApi = {
  generate: (payload: GenerateSRTRequest) =>
    apiClient.post<unknown, GenerateSRTResponse>('/api/subtitle/generate', payload),
  burn: (payload: BurnSubtitleRequest) =>
    apiClient.post<unknown, { job_id: string; status: string; stream_url: string; ws_url: string }>('/api/subtitle/burn', payload),
  exportOriginal: (payload: ExportOriginalRequest) =>
    apiClient.post<unknown, { job_id: string; status: string; stream_url: string; ws_url: string }>('/api/subtitle/export_original', payload),
  exportJianyingDraft: (payload: JianYingDraftExportRequestApi) =>
    apiClient.post<unknown, JianYingDraftExportResponseApi>('/api/subtitle/export_jianying_draft', payload),
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

// 视频总结
export type SummaryMode = 'asr' | 'vlm' | 'asr_vlm'

export interface SummaryTemplate {
  id: string
  name: string
  description?: string | null
  system_prompt: string
  user_prompt_template: string
  output_schema_hint?: string | null
  created_at: string
  updated_at: string
}

export interface SummaryGenerateRequest {
  video_id: string
  mode: SummaryMode
  /** 固定为后端内置 `user_builtin_note`，可不传 */
  template_id?: string
  user_goal: string
  extra_instructions?: string
  chunk_max_chars?: number
  chunk_overlap_chars?: number
  max_chunks?: number
  prompt_vars?: Record<string, any>
}

export interface VideoSummary {
  id: string
  video_id: string
  template_id: string
  mode: SummaryMode
  status: string
  input_fingerprint?: string | null
  summary_json?: any | null
  summary_markdown?: string | null
  prompt_snapshot_json?: any | null
  created_at: string
  updated_at: string
}

/** 智能视频大纲（视频总结页；结果存库） */
export interface SmartOutlineTopic {
  title: string
  start_sec: number
  end_sec: number
  summary?: string | null
}

export interface SmartOutlineClipScore {
  clip_id: string
  start_time: number
  end_time: number
  excitement: number
  reason?: string | null
}

export interface SmartOutlineMeta {
  context_clip_count: number
  clips_with_asr: number
  clips_with_vlm: number
  note: string
}

export interface SmartOutlineResponse {
  video_id: string
  video_title: string
  outline_markdown: string
  topics: SmartOutlineTopic[]
  clip_scores: SmartOutlineClipScore[]
  meta: SmartOutlineMeta
}

export interface SmartOutlineBundle {
  outline: SmartOutlineResponse | null
  updated_at: string | null
}

export type SmartOutlineGenerateResponse = SmartOutlineResponse & { updated_at: string }

export type SummaryAskSource = 'note' | 'outline' | 'both'

export interface SummaryAskMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface SummaryAskRequest {
  question: string
  source?: SummaryAskSource
  history?: SummaryAskMessage[]
}

export const summaryApi = {
  templates: () => apiClient.get<unknown, SummaryTemplate[]>('/api/summary/templates'),
  generate: (payload: SummaryGenerateRequest) => apiClient.post<unknown, VideoSummary>('/api/summary/generate', payload),
  generateStream: (payload: SummaryGenerateRequest): Promise<Response> =>
    fetch(`${API_BASE_URL}/api/summary/generate-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  latest: (videoId: string, params?: { template_id?: string; mode?: SummaryMode }) =>
    apiClient.get<unknown, VideoSummary | null>(`/api/summary/videos/${videoId}/latest`, { params }),
  update: (summaryId: string, payload: { summary_json?: any; summary_markdown?: string; source?: 'user' | 'llm' }) =>
    apiClient.patch<unknown, VideoSummary>(`/api/summary/${summaryId}`, payload),
  smartOutlineGet: (videoId: string) =>
    apiClient.get<unknown, SmartOutlineBundle>(`/api/summary/videos/${videoId}/smart-outline`),
  smartOutlineGenerate: (videoId: string, params?: { max_clips?: number }) =>
    apiClient.post<unknown, SmartOutlineGenerateResponse>(
      `/api/summary/videos/${videoId}/smart-outline/generate`,
      {},
      { params: { max_clips: params?.max_clips ?? 120 } },
    ),
  askStream: (videoId: string, payload: SummaryAskRequest): Promise<Response> =>
    fetch(`${API_BASE_URL}/api/summary/videos/${videoId}/ask-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
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
  replica_type?: 'short_video' | 'film_commentary' | 'scene_story' | null
  style_profile?: string | null
  quality_signals?: {
    coverage?: number
    coherence?: number
    density_stability?: number
  } | null
  template_preset_id?: string | null
  has_slots?: boolean
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

  generateTemplate: (
    videoId: string,
    payload?: {
      skip_vlm?: boolean
      max_clips?: number
      replica_type?: 'short_video' | 'film_commentary' | 'scene_story'
      style_profile?: string
      quality_mode?: 'balanced' | 'high_quality'
    }
  ) =>
    apiClient.post<unknown, ReplicaTemplateDraftResponse>(`/api/replica/${videoId}/generate-template`, payload ?? {}),

  confirmTemplate: (templateId: string, payload: { name?: string; template_guide: string; template_json?: any }) =>
    apiClient.post<unknown, ReplicaTemplateConfirmedResponse>(`/api/replica/template/${templateId}/confirm`, payload),

  getTemplate: (templateId: string) =>
    apiClient.get<unknown, any>(`/api/replica/template/${templateId}`),

  listTemplates: (params?: {
    q?: string
    status?: 'draft' | 'confirmed'
    replica_type?: 'short_video' | 'film_commentary' | 'scene_story'
    style_profile?: string
    sort?: 'updated_desc' | 'created_desc'
    page?: number
    page_size?: number
  }) =>
    apiClient.get<unknown, ReplicaTemplateListResponse>('/api/replica/templates', { params }),

  deleteTemplate: (templateId: string) =>
    apiClient.delete<unknown, { ok: boolean; template_id: string }>(`/api/replica/template/${templateId}`),

  renameTemplate: (templateId: string, name: string) =>
    apiClient.patch<unknown, { ok: boolean; template_id: string; name: string }>(`/api/replica/template/${templateId}`, { name }),

  /**
   * 从库内已处理完成的视频直接生成复刻模板（跳过下载/处理阶段，复用 clips 全字段）。
   * 等价于 generateTemplate，但语义上明确用于"库生成"入口。
   */
  generateFromExisting: (
    videoId: string,
    payload?: {
      skip_vlm?: boolean
      max_clips?: number
      replica_type?: 'short_video' | 'film_commentary' | 'scene_story'
      style_profile?: string
      quality_mode?: 'balanced' | 'high_quality'
    }
  ) =>
    apiClient.post<unknown, ReplicaTemplateDraftResponse>(`/api/replica/${videoId}/generate-template`, payload ?? {}),
}

export const ttsApi = {
  synthesize: (payload: TTSRequest) => apiClient.post<unknown, TTSResponse>('/api/tts/synthesize', payload),
  listVoices: (locale?: string) => apiClient.get<unknown, VoiceInfo[]>(`/api/tts/voices${locale ? `?locale=${locale}` : ''}`),
  audioUrl: (filename: string) => `${API_BASE_URL}/api/tts/audio/${filename}`,
}

export interface AudioMatchAsrSegment {
  start: number
  end: number
  text: string
}

export interface AudioMatchTranscribeResponse {
  source_filename: string
  wav_filename: string | null
  text: string
  segments: AudioMatchAsrSegment[]
  duration_sec: number
  provider: string
}

export const audioMatchApi = {
  transcribe: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<unknown, AudioMatchTranscribeResponse>('/api/audio-match/transcribe', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600_000,
    })
  },
  slice: (payload: { source_filename: string; slices: { start_sec: number; end_sec: number }[] }) =>
    apiClient.post<unknown, { filenames: string[] }>('/api/audio-match/slice', payload),
  sourceUrl: (filename: string) => `${API_BASE_URL}/api/audio-match/source/${encodeURIComponent(filename)}`,
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
  step: 'split' | 'extract_frames' | 'asr' | 'vlm' | 'enrich' | 'embed' | 'done' | 'error'
  status: 'running' | 'done' | 'error' | 'skip'
  message: string
  detail: Record<string, unknown>
}

export type MatchMode = 'auto' | 'vector' | 'text' | 'llm_only'

export interface MatchRequest {
  query: string
  top_k?: number
  top_n?: number
  video_ids?: string[] | null
  /**
   * 单次匹配模式覆盖（auto/vector/text/llm_only）。
   * 不传则用后端全局 match_mode 配置。
   * 旁白/解说场景前端会自动传 llm_only（跨层语义对齐，命中率更高）。
   */
  match_mode?: MatchMode
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
  /** Timeline Engine 长视频参数（任务级） */
  content_style?: 'generic' | 'ecommerce' | 'voiceover' | 'commentary'
  events_max_clips_per_batch?: number
  events_max_chars_per_batch?: number
  events_batch_overlap_clips?: number
  events_max_batches?: number
}

/** 混剪段落视觉随机变换（成片 FFmpeg / 剪映 ClipSettings / 剪辑台 CSS 预览共用） */
export interface SegmentVisualEffectApi {
  zoom?: number | null
  mirror?: boolean
  rotation_deg?: number | null
  color_intensity?: number | null
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
  /** true：成片跳过该段；字幕与拼接仅按未弃用段落顺序连续排布 */
  exclude_from_output?: boolean
  start_time_sec: number
  end_time_sec: number
  /** 用户手动覆盖该段在成片中的时长（秒）。用于“更可控”的段落时长/字幕节奏。 */
  override_duration_sec?: number | null
  clip_start_offset_sec?: number | null
  /** 口播快剪合并段：多 clip 顺序裁剪拼接，与 realize 管线一致 */
  clip_trims?: SubtitleClipTrimPart[]
  audio_mode: 'original' | 'tts' | 'mute'
  subtitle?: {
    strategy: 'auto' | 'asr' | 'rewrite' | 'none'
    text: string
    source: 'asr' | 'llm' | 'user'
    timing_hint?: { start: number; end: number }
  }
  visual_effect?: SegmentVisualEffectApi | null
}

export interface AutoEditBgmPlanApi {
  enabled: boolean
  source?: 'library' | 'user' | 'ai'
  track_id?: string | null
  track_ids?: string[]
  track_volumes_db?: Record<string, number>
  volume_db?: number
  loop?: boolean
  fade_in_sec?: number
  fade_out_sec?: number
  timeline_segments?: BgmTimelineSegmentApi[]
}

export interface AutoEditPlanQualityScoresApi {
  hook: number
  info_density: number
  emotion_curve: number
  rhythm: number
  /** 越高表示素材/文案重复越少（新颖度） */
  repetition: number
  platform_fit: number
}

export interface AutoEditPlanQualityApi {
  scores: AutoEditPlanQualityScoresApi
  overall: number
  grade: string
  summary: string
  reasons: string[]
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
  postprocess?: MixPostprocessConfigApi | null
  quality?: AutoEditPlanQualityApi | null
  production_profile?: import('./agent-types').ProductionProfileApi | null
  audio_summary?: import('./plan-audio-summary').PlanAudioSummaryApi | null
}

export interface AutoEditPlanResponseApi {
  plans: AutoEditPlanApi[]
}

export interface AutoEditPlanSessionResponseApi {
  session_id: string
  stream_url: string
}

export type MixAudioModeApi = 'keep_original' | 'mute_all_original'
export type MuteAudioTrackApi = 'ai_tts_asr' | 'ai_tts_llm' | 'bgm_only' | 'ai_tts'

export interface MixVisualRandomConfigApi {
  enable_zoom: boolean
  zoom_probability: number
  zoom_ratio_min: number
  zoom_ratio_max: number
  zoom_min_interval_segments: number
  enable_mirror: boolean
  mirror_probability: number
  enable_rotation: boolean
  rotation_probability: number
  rotation_deg_min: number
  rotation_deg_max: number
  enable_color: boolean
  color_probability: number
  color_intensity_min: number
  color_intensity_max: number
}

export interface MixOverlayVideoConfigApi {
  enabled: boolean
  path?: string | null
  opacity: number
  volume: number
}

export interface MixUserBgmConfigApi {
  enabled: boolean
  path?: string | null
  volume: number
}

export interface MixAntiDetectVideoConfigApi {
  enabled: boolean
  enable_inpaint: boolean
  inpaint_strength: number
  enable_displacement: boolean
  displacement_px_max: number
  enable_color_shift: boolean
  color_shift_max: number
  enable_frame_ops: boolean
  frame_drop_probability: number
  frame_dup_probability: number
  enable_scale_jitter: boolean
  scale_jitter_max: number
  enable_pixel_noise: boolean
  pixel_noise_sigma: number
  enable_crawl: boolean
  crawl_amplitude_px: number
}

export interface MixAntiDetectAudioConfigApi {
  enabled: boolean
  enable_fingerprint_obfusc: boolean
  noise_floor_db: number
  enable_phase_eq: boolean
  enable_segment_speed: boolean
  speed_variation: number
  enable_reverb_pitch: boolean
  pitch_semitones: number
  reverb_mix: number
}

export interface MixAntiDetectSchedulerConfigApi {
  random_seed?: string | null
  loop_iterations: number
  loop_gain: number
  output_format: 'mp4' | 'mkv'
}

export interface MixAntiDetectConfigApi {
  enabled: boolean
  video?: MixAntiDetectVideoConfigApi
  audio?: MixAntiDetectAudioConfigApi
  scheduler?: MixAntiDetectSchedulerConfigApi
}

export interface MixPostprocessConfigApi {
  visual_random?: MixVisualRandomConfigApi | null
  overlay_video?: MixOverlayVideoConfigApi | null
  user_bgm?: MixUserBgmConfigApi | null
  anti_detect?: MixAntiDetectConfigApi | null
}

export interface MixClipFilterConfigApi {
  min_duration_sec?: number
  max_duration_sec?: number
  trim_head_sec?: number
  trim_tail_sec?: number
}

export interface MixEditPlanRequestApi {
  video_ids: string[]
  mix_audio_mode: MixAudioModeApi
  mute_audio_track?: MuteAudioTrackApi
  target_duration_sec?: number
  user_prompt?: string
  tts_align?: TtsVideoAlignConfigApi
  postprocess?: MixPostprocessConfigApi
  clip_filter?: MixClipFilterConfigApi
}

export type VoiceoverQuickCutStrategyApi = 'asr_fast' | 'standard' | 'semantic' | 'audio_activity_fast'

export interface VoiceoverAudioActivityConfigApi {
  activity_db_threshold?: number
  activity_min_silence_sec?: number
  activity_min_keep_sec?: number
  activity_merge_gap_sec?: number
  activity_head_pad_sec?: number
  activity_tail_pad_sec?: number
}

export type TtsVideoAlignPolicyApi =
  | 'freeze_last_frame'
  | 'preserve_video_duration'
  | 'loop_video_to_cover'
  | 'loop_playlist_to_cover'
  | 'stretch_audio'
  | 'stretch_video'

export interface TtsVideoAlignConfigApi {
  policy: TtsVideoAlignPolicyApi
  max_audio_atempo?: number
  min_audio_atempo?: number
  max_video_pts_factor?: number
  min_video_pts_factor?: number
  /** false=仅句号/换行分条；true=再按逗号/顿号拆短条 */
  split_narration_by_sentence?: boolean
}

export type VideoDubContentSourceApi = 'asr_rewrite' | 'asr_literal' | 'vlm_narrate' | 'auto'

export interface VideoDubPlanRequestApi {
  video_ids: string[]
  content_source: VideoDubContentSourceApi
  user_prompt?: string
  preserve_gaps?: boolean
  tts_align?: TtsVideoAlignConfigApi
}

export interface VoiceoverQuickCutRequestApi {
  video_ids: string[]
  strategy: VoiceoverQuickCutStrategyApi
  user_prompt?: string
  /** 成片目标总时长（秒）；standard/semantic 生效；不传时尝试从 user_prompt 解析（如「2分钟」「120秒」） */
  target_duration_sec?: number
  /** 默认 false：同一 video 源绝对时间重叠（含跨 clip）时按成片顺序裁切，避免重复播放 */
  allow_overlapping_source_timeline?: boolean
  /** strategy=audio_activity_fast 时生效：音频活动检测参数 */
  activity_db_threshold?: number
  activity_min_silence_sec?: number
  activity_min_keep_sec?: number
  activity_merge_gap_sec?: number
  activity_head_pad_sec?: number
  activity_tail_pad_sec?: number
  /** strategy=audio_activity_fast 时可选：前端预计算的“保留区间”（绝对时间秒） */
  activity_keep_ranges?: Array<{ video_id: string; start: number; end: number }>
  /** 口播快剪（asr_fast/standard/semantic）：每段句头多保留秒数，保留说话间隙；默认 0 */
  asr_head_pad_sec?: number
  /** 口播快剪（asr_fast/standard/semantic）：每段句尾多保留秒数；默认 0 */
  asr_tail_pad_sec?: number
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
  mixEditPlan: (payload: MixEditPlanRequestApi) =>
    apiClient.post<unknown, AutoEditPlanResponseApi>('/api/auto-edit/mix-edit-plan', payload),
  mixUploadAsset: (file: File, kind: 'overlay' | 'bgm' | 'auto' = 'auto') => {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post<unknown, { path: string; stored_path: string; filename: string; kind: string }>(
      `/api/auto-edit/mix-upload-asset?kind=${encodeURIComponent(kind)}`,
      formData,
      formDataPostConfig(),
    )
  },
  videoDubPlan: (payload: VideoDubPlanRequestApi) =>
    apiClient.post<unknown, AutoEditPlanResponseApi>('/api/auto-edit/video-dub-plan', payload),
  realize: (payload: {
    plan: AutoEditPlanApi
    project_name?: string
    include_subtitle?: boolean
    style?: import('./subtitle-types').SubtitleStyle
    force_tts_pipeline?: boolean
    tts_align?: TtsVideoAlignConfigApi | null
    production_profile?: import('./agent-types').ProductionProfileApi | null
  }) =>
    apiClient.post<
      unknown,
      { job_id: string; status: string; stream_url: string; ws_url: string }
    >('/api/auto-edit/realize', payload),
  exportJianyingDraft: (payload: {
    plan: AutoEditPlanApi
    project_name?: string
    include_subtitle?: boolean
    style?: import('./subtitle-types').SubtitleStyle
    force_tts_pipeline?: boolean
    tts_align?: TtsVideoAlignConfigApi | null
  }) =>
    apiClient.post<unknown, JianYingDraftExportResponseApi>('/api/auto-edit/export-jianying-draft', payload),
}

/** 文案 + Pexels / 本地素材成片 */
export interface ScriptStockPexelsVideoFileApi {
  quality: string
  width: number
  height: number
  link: string
}

export interface ScriptStockPexelsVideoApi {
  id: number
  width: number
  height: number
  duration: number
  image: string
  user_name?: string
  video_files: ScriptStockPexelsVideoFileApi[]
}

export interface ScriptStockPexelsImageApi {
  id: number
  width: number
  height: number
  image: string
  user_name?: string
}

export type ScriptStockAudioMode = 'tts_only' | 'original_only' | 'mix'

export type ScriptStockTimelineMode = 'follow_narration' | 'follow_material'

export type ScriptStockVideoExtendPolicy = 'loop_video_to_cover' | 'freeze_last_frame'

export type ScriptStockMaterialTtsFill = 'pad_silence' | 'loop_audio'

export type ScriptStockMaterialTtsLonger = 'trim_tts' | 'stretch_audio'

export interface ScriptStockPexelsCacheItemApi {
  pexels_video_id: number
  media_type?: 'image' | 'video'
  stored_rel_path: string
  filename: string
  size_bytes: number
  mtime: number
  /** 下载时记录的搜索词 */
  search_query?: string
  /** Pexels 缩略图（外链可能过期） */
  pexels_image?: string
  /** Pexels 标注时长（秒） */
  duration_sec?: number
}

export interface ScriptStockPixabayVideoApi {
  id: number
  width: number
  height: number
  duration: number
  image: string
  user_name?: string
  tags?: string
  videos: Record<string, { url: string; width: number; height: number; size?: number; thumbnail?: string }>
}

export interface ScriptStockPixabayImageApi {
  id: number
  width: number
  height: number
  image: string
  user_name?: string
  tags?: string
}

export interface ScriptStockPixabayCacheItemApi {
  pixabay_video_id: number
  media_type?: 'image' | 'video'
  stored_rel_path: string
  filename: string
  size_bytes: number
  mtime: number
  search_query?: string
  preview_image?: string
  duration_sec?: number
}

export interface ScriptStockUnsplashPhotoApi {
  id: string
  width: number
  height: number
  description?: string
  image: string
  user_name?: string
  color?: string
}

export interface ScriptStockUnsplashCacheItemApi {
  unsplash_photo_id: string
  media_type?: 'image' | 'video'
  stored_rel_path: string
  filename: string
  size_bytes: number
  mtime: number
  search_query?: string
  preview_image?: string
  duration_sec?: number
}

export type ScriptStockOnlineProvider = 'pexels' | 'pixabay' | 'unsplash'

export interface ScriptStockComposeSegmentApi {
  kind: 'library' | 'pexels' | 'pixabay' | 'unsplash'
  video_id?: string | null
  /** 本地多段按顺序拼接（仅「仅 TTS」）；非空时优先于 video_id */
  library_video_ids?: string[] | null
  stored_rel_path?: string | null
  /** Pexels 多文件按顺序拼接（仅「仅 TTS」）；非空时优先于 stored_rel_path */
  pexels_stored_rel_paths?: string[] | null
  pixabay_stored_rel_paths?: string[] | null
  unsplash_stored_rel_paths?: string[] | null
  /** 与 library_video_ids 同序；本地素材选用区间（秒），不传则服务端按整文件探测 */
  library_trims?: Array<{ in_sec: number; out_sec: number }> | null
  /** 该段配音文案；tts_only / mix 时使用 */
  text?: string | null
}

export const scriptStockApi = {
  split: (body: { script: string; mode?: 'paragraph' | 'line' }) =>
    apiClient.post<unknown, { segments: string[] }>('/api/script-stock/split', body),
  generateScript: (body: { topic: string; style_hint?: string; num_paragraphs?: number }) =>
    apiClient.post<unknown, { script: string }>('/api/script-stock/generate-script', body),
  suggestQueries: (body: { segments: string[] }) =>
    apiClient.post<unknown, { queries: string[] }>('/api/script-stock/suggest-queries', body),
  pexelsSearch: (params: { query: string; page?: number; per_page?: number }) =>
    apiClient.get<unknown, {
      page: number
      per_page: number
      total_results: number
      videos: ScriptStockPexelsVideoApi[]
      images: ScriptStockPexelsImageApi[]
    }>('/api/script-stock/pexels/search', { params }),
  pexelsDownload: (body: {
    pexels_media_id: number
    media_type?: 'video' | 'image'
    preferred_quality?: 'medium' | 'hd' | 'sd' | 'hls'
    /** 当前段搜索使用的关键词，便于缓存列表展示 */
    search_query?: string
  }) =>
    apiClient.post<unknown, { stored_rel_path: string; public_url: string; filename: string }>(
      '/api/script-stock/pexels/download',
      body,
    ),
  pexelsListCache: () =>
    apiClient.get<unknown, { items: ScriptStockPexelsCacheItemApi[] }>('/api/script-stock/pexels/cache'),
  pexelsDeleteFile: (body: { stored_rel_path: string }) =>
    apiClient.post<unknown, { ok: boolean }>('/api/script-stock/pexels/delete-file', body),
  pexelsClearCache: () =>
    apiClient.post<unknown, { ok: boolean; deleted_files: number }>('/api/script-stock/pexels/clear-cache'),
  pixabaySearch: (params: { query: string; page?: number; per_page?: number }) =>
    apiClient.get<unknown, {
      page: number
      per_page: number
      total_results: number
      videos: ScriptStockPixabayVideoApi[]
      images: ScriptStockPixabayImageApi[]
    }>('/api/script-stock/pixabay/search', { params }),
  pixabayDownload: (body: {
    pixabay_media_id: number
    media_type?: 'video' | 'image'
    preferred_quality?: 'large' | 'medium' | 'small' | 'tiny'
    search_query?: string
  }) =>
    apiClient.post<unknown, { stored_rel_path: string; public_url: string; filename: string }>(
      '/api/script-stock/pixabay/download',
      body,
    ),
  pixabayListCache: () =>
    apiClient.get<unknown, { items: ScriptStockPixabayCacheItemApi[] }>('/api/script-stock/pixabay/cache'),
  pixabayDeleteFile: (body: { stored_rel_path: string }) =>
    apiClient.post<unknown, { ok: boolean }>('/api/script-stock/pixabay/delete-file', body),
  pixabayClearCache: () =>
    apiClient.post<unknown, { ok: boolean; deleted_files: number }>('/api/script-stock/pixabay/clear-cache'),
  unsplashSearch: (params: { query: string; page?: number; per_page?: number }) =>
    apiClient.get<unknown, {
      page: number
      per_page: number
      total_results: number
      photos: ScriptStockUnsplashPhotoApi[]
    }>('/api/script-stock/unsplash/search', { params }),
  unsplashDownload: (body: {
    unsplash_photo_id: string
    search_query?: string
  }) =>
    apiClient.post<unknown, { stored_rel_path: string; public_url: string; filename: string }>(
      '/api/script-stock/unsplash/download',
      body,
    ),
  unsplashListCache: () =>
    apiClient.get<unknown, { items: ScriptStockUnsplashCacheItemApi[] }>('/api/script-stock/unsplash/cache'),
  unsplashDeleteFile: (body: { stored_rel_path: string }) =>
    apiClient.post<unknown, { ok: boolean }>('/api/script-stock/unsplash/delete-file', body),
  unsplashClearCache: () =>
    apiClient.post<unknown, { ok: boolean; deleted_files: number }>('/api/script-stock/unsplash/clear-cache'),
  compose: (body: {
    segments: ScriptStockComposeSegmentApi[]
    project_name?: string
    audio_mode?: ScriptStockAudioMode
    tts_volume_db?: number
    original_volume_db?: number
    tts_voice?: string | null
    tts_rate?: string | null
    tts_volume?: string | null
    timeline_mode?: ScriptStockTimelineMode
    video_extend_policy?: ScriptStockVideoExtendPolicy
    material_tts_fill?: ScriptStockMaterialTtsFill
    material_tts_longer?: ScriptStockMaterialTtsLonger
    include_subtitle?: boolean
    subtitle_style?: SubtitleStyle
    bgm?: BgmMixConfigApi
  }) =>
    apiClient.post<unknown, { job_id: string; status: string; stream_url: string; ws_url: string }>(
      '/api/script-stock/compose',
      body,
    ),
  /** 请求体与 compose 相同；仅生成剪映草稿（未配置父目录时 ZIP+下载，已配置时直写本地目录） */
  exportJianyingDraft: (body: {
    segments: ScriptStockComposeSegmentApi[]
    project_name?: string
    audio_mode?: ScriptStockAudioMode
    tts_volume_db?: number
    original_volume_db?: number
    tts_voice?: string | null
    tts_rate?: string | null
    tts_volume?: string | null
    timeline_mode?: ScriptStockTimelineMode
    video_extend_policy?: ScriptStockVideoExtendPolicy
    material_tts_fill?: ScriptStockMaterialTtsFill
    material_tts_longer?: ScriptStockMaterialTtsLonger
    include_subtitle?: boolean
    subtitle_style?: SubtitleStyle
    bgm?: BgmMixConfigApi
  }) =>
    apiClient.post<unknown, JianYingDraftExportResponseApi>('/api/script-stock/export-jianying-draft', body),
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
  uploaded_at?: string | null
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
  upload: (file: File, meta?: { title?: string; mood?: string; tags?: string[] }) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('client_filename', file.name || '')
    if (meta?.title) formData.append('title', meta.title)
    if (meta?.mood) formData.append('mood', meta.mood)
    if (meta?.tags?.length) formData.append('tags', meta.tags.join(','))
    return apiClient.post<unknown, BgmTrack>('/api/bgm/upload', formData, formDataPostConfig())
  },
  update: (id: string, payload: BgmUpdatePayload) =>
    apiClient.patch<unknown, BgmTrack>(`/api/bgm/tracks/${id}`, payload),
  delete: (id: string) => apiClient.delete(`/api/bgm/tracks/${id}`),
}

/** 浏览器录音 → 后端 ASR；可选再走 LLM 按「意图」整理 */
export interface VoiceTranscribeResponse {
  text: string
  segments?: Array<{ start: number; end: number; text: string }>
  slot?: number
  provider?: string
}

export interface VoiceRefineBody {
  transcript: string
  intent: string
  current_value?: string
  mode: 'replace' | 'append'
}

export const voiceInputApi = {
  transcribe: (blob: Blob, filename = 'recording.webm') => {
    const fd = new FormData()
    fd.append('file', blob, filename)
    return apiClient.post<unknown, VoiceTranscribeResponse>(
      '/api/voice/transcribe',
      fd,
      formDataPostConfig(),
    )
  },
  refine: (body: VoiceRefineBody) =>
    apiClient.post<unknown, { text: string }>('/api/voice/refine', body),
}

/** 影视解说专区 */
export type FilmMode = 'precise' | 'lightweight'
export type FilmStyle = 'suspense' | 'humor' | 'deep' | 'fast' | 'wilderness'
export type FilmJobStatus =
  | 'pending'
  | 'parsing'
  | 'scripting'
  | 'aligning'
  | 'planning'
  | 'rendering'
  | 'done'
  | 'failed'
  | 'cancelled'

export interface FilmSentence {
  index: number
  text: string
  tag?: string | null
}

export interface FilmAlignment {
  sentence_index: number
  clip_id: string
  video_id: string
  start_time: number
  end_time: number
  score: number
  reason: string
}

export interface FilmCommentaryJob {
  id: string
  video_id: string
  video_name?: string | null
  status: FilmJobStatus
  current_step?: string | null
  mode: FilmMode
  style: FilmStyle
  target_duration_sec: number
  auto_render: boolean
  include_subtitle: boolean
  progress: Record<string, { status: string; message: string; detail?: Record<string, unknown> }>
  error_message?: string | null
  storyline?: Record<string, string> | null
  sentences: FilmSentence[]
  alignments: FilmAlignment[]
  plan?: AutoEditPlanApi | null
  output_url?: string | null
  output_filename?: string | null
  created_at: string
  updated_at: string
  finished_at?: string | null
}

export interface FilmPromptOverrides {
  summarize_system_prompt?: string
  screenplay_system_prompt?: string
  screenplay_user_prompt_template?: string
}

export interface FilmPromptTemplates {
  style: FilmStyle
  style_hint: string
  target_duration_sec: number
  mode: FilmMode
  summarize_system_prompt: string
  screenplay_system_prompt: string
  screenplay_user_prompt_template: string
}

export interface FilmCommentaryCreateBody {
  video_id: string
  mode?: FilmMode
  style?: FilmStyle
  target_duration_sec?: number
  auto_render?: boolean
  include_subtitle?: boolean
  prompt_overrides?: FilmPromptOverrides
}

export const filmCommentaryApi = {
  promptTemplates: (params: {
    style?: FilmStyle
    mode?: FilmMode
    target_duration_sec?: number
  }) =>
    apiClient.get<unknown, FilmPromptTemplates>('/api/film/prompt-templates', { params }),
  list: (limit = 30) =>
    apiClient.get<unknown, { items: FilmCommentaryJob[]; total: number }>('/api/film/jobs', {
      params: { limit },
    }),
  get: (jobId: string) =>
    apiClient.get<unknown, FilmCommentaryJob>(`/api/film/jobs/${jobId}`),
  create: (body: FilmCommentaryCreateBody) =>
    apiClient.post<unknown, FilmCommentaryJob>('/api/film/jobs', body),
  cancel: (jobId: string) =>
    apiClient.post<unknown, { ok: boolean; job_id: string }>(`/api/film/jobs/${jobId}/cancel`),
  retry: (jobId: string) =>
    apiClient.post<unknown, FilmCommentaryJob>(`/api/film/jobs/${jobId}/retry`),
}

// ── 一键发布 ─────────────────────────────────────────────────────────────
export interface PublishStatusResp {
  ready: boolean
  browser: {
    ready: boolean
    kind: string
    label: string
    channel: string | null
    has_local_chrome: boolean
    has_local_edge: boolean
    has_bundled_chromium: boolean
  }
  platforms: Array<{
    platform: string
    label: string
    implemented: boolean
    risk: string
    has_account: boolean
  }>
  implemented_platforms: string[]
}

export interface PublishAccountResp {
  platform: string
  account: string
  login_status: string
  display_name: string | null
  last_login_at: string | null
  last_used_at: string | null
  last_error: string | null
}

export interface PublishTaskResp {
  id: string
  video_path: string
  video_name: string | null
  status: string
  pid: number | null
  items_json: unknown
  progress_json: unknown
  result_json: unknown
  log: string
  running?: boolean
  created_at: string
  updated_at: string
}

export interface CreatePublishTaskBody {
  video_path: string
  items: Array<{
    platform: string
    account: string
    title: string
    description: string
    tags: string[]
    cover_path: string | null
    publish_strategy: 'immediate' | 'scheduled'
    publish_date: string | null
  }>
  // 是否无头模式（true=后台无界面；false=显示浏览器窗口，便于排查/手动兜底）
  headless?: boolean
}

export const publishApi = {
  status: () => apiClient.get<unknown, PublishStatusResp>('/api/publish/status'),
  listAccounts: (platform?: string) =>
    apiClient.get<unknown, { accounts: PublishAccountResp[] }>('/api/publish/accounts', {
      params: platform ? { platform } : undefined,
    }),
  login: (platform: string, account = 'main') =>
    apiClient.post<unknown, { message: string; account: string }>(
      `/api/publish/accounts/${platform}/login`,
      { account },
    ),
  checkLogin: (platform: string, account = 'main') =>
    apiClient.post<unknown, { platform: string; account: string; valid: boolean; message?: string }>(
      `/api/publish/accounts/${platform}/check`,
      { account },
    ),
  deleteAccount: (platform: string, account: string) =>
    apiClient.delete<unknown, { removed: boolean; platform: string; account: string }>(
      `/api/publish/accounts/${platform}/${account}`,
    ),
  // 更新账号自定义显示名称（备注/别名）；空串清除自定义名
  updateAccount: (
    platform: string,
    account: string,
    body: { display_name: string },
  ) =>
    apiClient.patch<
      unknown,
      { platform: string; account: string; display_name: string | null; updated: boolean }
    >(`/api/publish/accounts/${platform}/${account}`, body),
  createTask: (body: CreatePublishTaskBody) =>
    apiClient.post<unknown, { task_id: string; status: string; message: string }>(
      '/api/publish/tasks',
      body,
    ),
  listTasks: (limit = 50, offset = 0) =>
    apiClient.get<unknown, { tasks: PublishTaskResp[]; total: number }>('/api/publish/tasks', {
      params: { limit, offset },
    }),
  getTask: (taskId: string) => apiClient.get<unknown, PublishTaskResp>(`/api/publish/tasks/${taskId}`),
  cancelTask: (taskId: string) =>
    apiClient.delete<unknown, { cancelled: boolean; message?: string }>(
      `/api/publish/tasks/${taskId}`,
    ),
  // AI 生成发布文案（标题/描述/标签）。ASR 优先 + VLM 兜底，结果缓存到 renders 表
  // user_prompt：用户自定义提示词（语言/特定指引/修正/特定要求等），优先级最高，覆盖默认风格
  generateCopy: (
    renderId: string,
    body: { platform?: string; tone?: string; user_prompt?: string },
  ) =>
    apiClient.post<unknown, GenerateCopyResp>(
      `/api/publish/renders/${renderId}/generate-copy`,
      body,
    ),
}

// ── AI 生成文案响应 ───────────────────────────────────────────────────────
export interface GenerateCopyResp {
  title: string
  description: string
  tags: string[]
  source: {
    material_title: boolean
    plan: boolean
    asr: boolean
    vlm: boolean
    asr_note?: string | null
  }
  cached: { asr: boolean; vlm: boolean }
  /** 平台字数硬约束（供前端展示「x/上限」）*/
  limits?: {
    title_max: number
    desc_max: number
    tags_max: number
    lang: string
  }
  /** 实际字数（中文按汉字数、英文按字符数）*/
  lengths?: { title: number; description: number; tags: number }
  /** 是否触发了兜底截断（LLM 超长被截）*/
  trimmed?: boolean
}

// ── 成片管理 ──────────────────────────────────────────────────────────────
export interface RenderItemResp {
  id: string
  file_path: string
  public_url: string
  filename: string
  title: string | null
  source: string
  material_id: string | null
  duration: number
  thumbnail_path: string | null
  thumbnail_url: string | null
  thumbnail_api_url: string
  source_label: string
  video_url: string
  file_size: number
  created_at: string
  recorded_at: string
  // AI 文案生成相关元数据（渲染时携带 + 缓存）
  material_title?: string | null
  plan_json?: string | null
  asr_text?: string | null
  vlm_summary?: string | null
  ai_context_at?: string | null
}

export interface RenderListResp {
  items: RenderItemResp[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export const rendersApi = {
  list: (params?: { search?: string; source?: string; page?: number; page_size?: number }) =>
    apiClient.get<unknown, RenderListResp>('/api/renders', { params }),
  sources: () =>
    apiClient.get<unknown, { sources: Array<{ value: string; label: string }> }>(
      '/api/renders/sources',
    ),
  get: (id: string) => apiClient.get<unknown, RenderItemResp>(`/api/renders/${id}`),
  thumbnailUrl: (id: string) => `${API_BASE_URL}/api/renders/${id}/thumbnail`,
  videoUrl: (publicUrl: string) => `${API_BASE_URL}${publicUrl}`,
  delete: (id: string) =>
    apiClient.delete<unknown, { deleted: boolean; filename: string }>(`/api/renders/${id}`),
  scan: () => apiClient.post<unknown, { stats: Record<string, number> }>('/api/renders/scan'),
}
