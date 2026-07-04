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
