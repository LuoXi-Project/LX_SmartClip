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

export type ExportMode = 'zip' | 'merged'

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
export const clipStreamUrl = (id: string) => `${API_BASE}/api/videos/clips/${id}/stream`
export const audioSrc = (f: string) => `${API_BASE}/api/tts/audio/${f}`

export function fmt(s: number) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}
