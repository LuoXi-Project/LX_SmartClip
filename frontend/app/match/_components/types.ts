import type { MatchClip } from '@/lib/api'

export interface Segment {
  id: string
  text: string
  clips: MatchClip[]
  chosenIdx: number
  ttsFilename: string | null
  ttsLoading: boolean
  ttsError: string
  matchLoading: boolean
  matchError: string
  expanded: boolean
}

export interface SubtitleStyle {
  font_name: string
  font_size: number
  font_color: string
  outline_color: string
  outline_width: number
  shadow: number
  bold: boolean
  italic: boolean
  position: 'bottom' | 'top' | 'center'
  margin_v: number
  background: boolean
  max_chars_per_line: number
}

export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  font_name: 'Arial',
  font_size: 24,
  font_color: '#FFFFFF',
  outline_color: '#000000',
  outline_width: 2,
  shadow: 1,
  bold: false,
  italic: false,
  position: 'bottom',
  margin_v: 20,
  background: false,
  max_chars_per_line: 20,
}

export interface SRTEntry {
  index: number
  start: number
  end: number
  text: string
  clip_id: string
}

export type ExportMode = 'zip' | 'merged' | 'subtitle'

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
export const clipStreamUrl = (id: string) => `${API_BASE}/api/videos/clips/${id}/stream`
export const audioSrc = (f: string) => `${API_BASE}/api/tts/audio/${f}`

export function fmt(s: number) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}
