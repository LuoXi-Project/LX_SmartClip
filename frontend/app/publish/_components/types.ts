/** 发布模块的前端类型定义，与后端 api/publish.py 响应对齐。 */

export type PlatformName =
  | 'douyin'
  | 'xhs'
  | 'wxchannels'
  | 'bilibili'
  | 'kuaishou'
  | 'tiktok'
  | 'youtube'

/** 浏览器引擎命中情况（/api/publish/status.browser）。 */
export interface PublishBrowserStatus {
  ready: boolean
  kind: 'chrome' | 'msedge' | 'chromium' | 'none'
  label: string
  channel: string | null
  has_local_chrome: boolean
  has_local_edge: boolean
  has_bundled_chromium: boolean
}

/** 单个平台元信息。 */
export interface PlatformInfo {
  platform: PlatformName
  label: string
  implemented: boolean
  risk: 'low' | 'normal' | 'strict'
  has_account: boolean
}

/** /api/publish/status 响应。 */
export interface PublishStatus {
  ready: boolean
  browser: PublishBrowserStatus
  platforms: PlatformInfo[]
  implemented_platforms: PlatformName[]
}

/** 单个账号信息。 */
export interface PublishAccount {
  platform: PlatformName
  account: string
  login_status: 'logged_in' | 'logged_out' | 'expired'
  display_name: string | null
  last_login_at: string | null
  last_used_at: string | null
  last_error: string | null
}

/** 创建发布任务的单平台请求项。 */
export interface PublishItemRequest {
  platform: PlatformName
  account: string
  title: string
  description: string
  tags: string[]
  cover_path: string | null
  publish_strategy: 'immediate' | 'scheduled'
  publish_date: string | null
}

/** 发布任务记录（列表/详情）。 */
export interface PublishTask {
  id: string
  video_path: string
  video_name: string | null
  status:
    | 'pending'
    | 'running'
    | 'succeeded'
    | 'failed'
    | 'partial'
    | 'cancelled'
  pid: number | null
  items_json: PublishItemRequest[] | string
  progress_json: Record<string, unknown> | string | null
  result_json: Record<string, unknown> | string | null
  log: string
  running?: boolean
  created_at: string
  updated_at: string
}

/** 进度信息（worker stdout PROGRESS 行）。 */
export interface PublishProgress {
  ts?: string
  platform: string
  /** 账号标识（多账号矩阵时区分"谁在发"，worker 在账号任务边界 emit） */
  account?: string
  step?: string
  status?: 'running' | 'success' | 'failed' | 'skipped'
  pct?: number
  message?: string
  log?: string
}

// ── 成片（renders）类型 ────────────────────────────────────────────────────
export type RenderSource =
  | 'burn'
  | 'export_original'
  | 'realize'
  | 'film_commentary'
  | 'script_stock_compose'

// ── 平台字数硬约束（与后端 copy_generator._PLATFORM_SPECS 对齐） ──────────
// 用于前端输入框 maxLength + 字数计数器；权威值以后端返回的 limits 为准。
export interface PlatformSpec {
  title_max: number
  desc_max: number
  tags_max: number
  lang: 'zh-CN' | 'en'
}
export const PLATFORM_SPECS: Record<string, PlatformSpec> = {
  douyin: { title_max: 55, desc_max: 500, tags_max: 5, lang: 'zh-CN' },
  xhs: { title_max: 20, desc_max: 1000, tags_max: 10, lang: 'zh-CN' },
  bilibili: { title_max: 80, desc_max: 2000, tags_max: 10, lang: 'zh-CN' },
  wxchannels: { title_max: 1000, desc_max: 1000, tags_max: 6, lang: 'zh-CN' },
  kuaishou: { title_max: 100, desc_max: 500, tags_max: 4, lang: 'zh-CN' },
  tiktok: { title_max: 150, desc_max: 4000, tags_max: 6, lang: 'en' },
  youtube: { title_max: 100, desc_max: 5000, tags_max: 15, lang: 'en' },
}
const DEFAULT_SPEC: PlatformSpec = { title_max: 55, desc_max: 500, tags_max: 8, lang: 'zh-CN' }
export const getPlatformSpec = (p: string): PlatformSpec => PLATFORM_SPECS[p] || DEFAULT_SPEC

/** 按平台语言计字数：中文按汉字数（去空白）、英文按字符数。 */
export function countByLang(s: string, lang: 'zh-CN' | 'en'): number {
  if (!s) return 0
  if (lang === 'en') return s.length
  return s.replace(/\s+/g, '').length
}

/** 单个成片记录（/api/renders 响应项）。 */
export interface RenderItem {
  id: string
  file_path: string
  public_url: string
  filename: string
  title: string | null
  source: RenderSource | string
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

/** /api/renders 列表响应。 */
export interface RenderListResp {
  items: RenderItem[]
  total: number
  limit: number
  offset: number
}

/** 来源选项（/api/renders/sources）。 */
export interface RenderSourceOption {
  value: string
  label: string
}
