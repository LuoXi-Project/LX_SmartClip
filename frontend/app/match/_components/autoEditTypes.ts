export type AutoPlanStage = 'idle' | 'preparing' | 'connecting' | 'planning' | 'done' | 'failed'

export type ClipMeta = { video_id: string; start_time: number; end_time: number }

export type ClipMetaByClip = Record<string, ClipMeta>

export type SelectedPreviewState = {
  planId: string
  planTitle: string
  segmentId: string
  order: number
  clipId: string
  videoId: string | null
  source: 'video' | 'clip'
  startSec: number
  endSec: number
}

export type PreviewTimeline = {
  meta?: ClipMeta
  planStart: number
  planEnd: number
  absStart: number
  absEnd: number
  clipLocalEnd: number
  windowSemantic: 'clip_like' | 'timeline_like'
}
