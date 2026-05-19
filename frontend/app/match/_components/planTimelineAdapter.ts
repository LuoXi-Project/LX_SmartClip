import type { AutoEditPlanApi, AutoEditSegmentPlanApi, SegmentVisualEffectApi } from '@/lib/api'
import type { TimelineClipBlock, TimelineTrack } from '@/components/timeline-editor'
import { clipColorByIndex } from '@/components/timeline-editor'
import type { ClipMeta } from './autoEditTypes'
import { planSegmentPreviewAbsRange } from './planSegmentPreviewRange'

const MIN_SEG = 0.08

export type PlanSegmentLayout = {
  segmentId: string
  segIdx: number
  order: number
  timelineStart: number
  timelineEnd: number
  duration: number
  sourceStart: number
  sourceEnd: number
  clipId: string
  label: string
  subtitleText: string
  excluded: boolean
  visualEffect?: SegmentVisualEffectApi | null
}

export function segmentOutputDuration(
  s: AutoEditSegmentPlanApi,
  sourceStart: number,
  sourceEnd: number,
): number {
  if (typeof s.override_duration_sec === 'number' && s.override_duration_sec > 0) {
    return s.override_duration_sec
  }
  return Math.max(MIN_SEG, sourceEnd - sourceStart)
}

export function buildPlanSegmentLayouts(
  segments: AutoEditSegmentPlanApi[],
  clipMetaByClip: Record<string, ClipMeta | undefined>,
): PlanSegmentLayout[] {
  const layouts: PlanSegmentLayout[] = []
  let cursor = 0

  for (let segIdx = 0; segIdx < segments.length; segIdx++) {
    const s = segments[segIdx]
    const clipId = s.selected_clip_ids?.[0] || s.clip_group?.[0]?.clip_id || ''
    const cm = clipId ? clipMetaByClip[clipId] : undefined
    const { displayStart, displayEnd } = planSegmentPreviewAbsRange(s, cm)
    const dur = segmentOutputDuration(s, displayStart, displayEnd)
    const excluded = !!s.exclude_from_output

    const layout: PlanSegmentLayout = {
      segmentId: s.id,
      segIdx,
      order: s.order,
      timelineStart: cursor,
      timelineEnd: excluded ? cursor : cursor + dur,
      duration: dur,
      sourceStart: displayStart,
      sourceEnd: displayEnd,
      clipId,
      label: `#${s.order}`,
      subtitleText: s.subtitle?.text?.trim() || '',
      excluded,
      visualEffect: s.visual_effect ?? null,
    }

    if (!excluded) cursor += dur
    layouts.push(layout)
  }

  return layouts
}

export function planLayoutsToTracks(layouts: PlanSegmentLayout[]): {
  tracks: TimelineTrack[]
  totalDuration: number
} {
  const active = layouts.filter((l) => !l.excluded)
  const totalDuration = active.length ? active[active.length - 1].timelineEnd : 0.5

  const videoClips: TimelineClipBlock[] = []
  const subtitleClips: TimelineClipBlock[] = []
  const audioClips: TimelineClipBlock[] = []

  for (const l of layouts) {
    if (l.excluded) continue
    const base = {
      id: l.segmentId,
      timelineStart: l.timelineStart,
      timelineEnd: l.timelineEnd,
      sourceStart: l.sourceStart,
      sourceEnd: l.sourceEnd,
      segmentIndex: l.segIdx,
      clipId: l.clipId,
      excluded: false,
    }
    videoClips.push({ ...base, label: l.label, color: clipColorByIndex(l.segIdx) })
    audioClips.push({
      ...base,
      label: '原声',
      color: 'bg-emerald-600/40 border-emerald-500/50',
    })
    const subLabel = l.subtitleText
      ? l.subtitleText.slice(0, 14) + (l.subtitleText.length > 14 ? '…' : '')
      : '（无字幕）'
    subtitleClips.push({
      ...base,
      label: subLabel,
      subtitleText: l.subtitleText,
      color: l.subtitleText
        ? 'bg-amber-500/45 border-amber-400/55'
        : 'bg-slate-700/40 border-slate-600/50',
    })
  }

  return {
    tracks: [
      { id: 'video', kind: 'video', label: '视频', clips: videoClips },
      { id: 'audio', kind: 'audio', label: '音频', clips: audioClips },
      { id: 'subtitle', kind: 'subtitle', label: '字幕', clips: subtitleClips },
    ],
    totalDuration,
  }
}

export function getActiveLayouts(layouts: PlanSegmentLayout[]) {
  return layouts.filter((l) => !l.excluded)
}

export function getNextActiveLayout(layouts: PlanSegmentLayout[], current: PlanSegmentLayout) {
  const active = getActiveLayouts(layouts)
  const idx = active.findIndex((l) => l.segmentId === current.segmentId)
  if (idx < 0 || idx >= active.length - 1) return null
  return active[idx + 1]
}

/** 源素材时间 → 成片时间轴位置 */
export function sourceTimeToOutputTime(layout: PlanSegmentLayout, sourceTime: number) {
  const srcSpan = Math.max(MIN_SEG, layout.sourceEnd - layout.sourceStart)
  const rel = Math.min(1, Math.max(0, (sourceTime - layout.sourceStart) / srcSpan))
  return layout.timelineStart + rel * layout.duration
}

/** 成片时间轴播放头位置对应的字幕文案（预览叠加用） */
export function getSubtitleAtPlayhead(layouts: PlanSegmentLayout[], playheadSec: number): string | null {
  const hit = playheadToSourceTime(layouts, playheadSec)
  if (!hit || hit.layout.excluded) return null
  const text = hit.layout.subtitleText?.trim()
  return text || null
}

export function playheadToSourceTime(
  layouts: PlanSegmentLayout[],
  playheadSec: number,
): { layout: PlanSegmentLayout; sourceTime: number } | null {
  for (const l of layouts) {
    if (l.excluded) continue
    if (playheadSec >= l.timelineStart && playheadSec < l.timelineEnd) {
      const ratio = (playheadSec - l.timelineStart) / Math.max(l.duration, MIN_SEG)
      const srcSpan = l.sourceEnd - l.sourceStart
      return { layout: l, sourceTime: l.sourceStart + ratio * srcSpan }
    }
  }
  const last = [...layouts].reverse().find((l) => !l.excluded)
  if (last) return { layout: last, sourceTime: last.sourceEnd }
  return null
}

export function applyPlanClipResize(
  plan: AutoEditPlanApi,
  segIdx: number,
  edge: 'start' | 'end',
  sourceStart: number,
  sourceEnd: number,
  timelineDuration: number,
): AutoEditPlanApi {
  const segs = [...(plan.segments ?? [])]
  const cur = { ...segs[segIdx] }

  if (edge === 'end') {
    cur.end_time_sec = sourceEnd
    if (cur.subtitle?.timing_hint) {
      cur.subtitle = { ...cur.subtitle, timing_hint: { start: sourceStart, end: sourceEnd } }
    }
    cur.override_duration_sec = timelineDuration
  } else {
    cur.start_time_sec = sourceStart
    if (cur.subtitle?.timing_hint) {
      cur.subtitle = { ...cur.subtitle, timing_hint: { start: sourceStart, end: sourceEnd } }
    }
    cur.override_duration_sec = timelineDuration
  }

  segs[segIdx] = cur
  return { ...plan, segments: segs }
}
