import type { MatchClip } from '@/lib/api'
export type { SubtitleStyle, ExportMode } from '@/lib/subtitle-types'
export { DEFAULT_SUBTITLE_STYLE } from '@/lib/subtitle-types'

export interface Segment {
  id: string
  text: string
  clips: MatchClip[]
  chosenIdx: number
  /** 已按勾选顺序记录的 clip_id 列表（第一个为当前展示/主选） */
  selectedClipIds: string[]
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

// 为了兼容现有组件导入：同域默认值（空字符串 => 使用相对路径）
export const API_BASE = ''

export const clipStreamUrl = (id: string) => `/api/videos/clips/${id}/stream`
export const videoStreamUrl = (id: string) => `/api/videos/${id}/stream`
export const audioSrc = (f: string) => `/api/tts/audio/${f}`

export function fmt(s: number) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}
