import type { MatchClip } from '@/lib/api'
import { API_BASE_URL } from '@/lib/runtime-config'
export type { SubtitleStyle, ExportMode } from '@/lib/subtitle-types'
export { DEFAULT_SUBTITLE_STYLE } from '@/lib/subtitle-types'

/** 片段文件内使用区间（秒），相对该 clip 文件起点；导出时写入 clip_start_sec / duration_sec */
export type ClipTrimRange = { inSec: number; outSec: number }

export interface Segment {
  id: string
  text: string
  clips: MatchClip[]
  chosenIdx: number
  /** 已按勾选顺序记录的 clip_id 列表（第一个为当前展示/主选） */
  selectedClipIds: string[]
  /** 按 clip_id 记录出入点（无槽位数据时的回退；旧数据） */
  clipTrimByClipId?: Record<string, ClipTrimRange>
  /** 与 selectedClipIds 等长，第 i 条选用素材的出入点（同 clip_id 多次出现时各槽独立） */
  clipTrimSlots?: ClipTrimRange[]
  ttsFilename: string | null
  ttsLoading: boolean
  ttsError: string
  matchLoading: boolean
  matchError: string
  expanded: boolean
}

export interface SRTEntry {
  index: number
  start: number
  end: number
  text: string
  clip_id: string
}

// 兼容历史引用：不要在各处再自定义 base，统一走 `lib/runtime-config.ts`
export const API_BASE = API_BASE_URL

export const clipStreamUrl = (id: string) => `${API_BASE_URL}/api/videos/clips/${id}/stream`
export const videoStreamUrl = (id: string) => `${API_BASE_URL}/api/videos/${id}/stream`
export const videoAudioStreamUrl = (id: string) => `${API_BASE_URL}/api/videos/${id}/audio/stream`
export const audioSrc = (f: string) => `${API_BASE_URL}/api/tts/audio/${f}`

export function fmt(s: number) {
  const totalMs = Math.max(0, Math.round((Number.isFinite(s) ? s : 0) * 1000))
  const m = Math.floor(totalMs / 60000)
  const sec = Math.floor((totalMs % 60000) / 1000)
  const ms = totalMs % 1000
  return `${m}:${sec.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`
}
