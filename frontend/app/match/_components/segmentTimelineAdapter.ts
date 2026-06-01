import type { TimelineClipBlock, TimelineTrack } from '@/components/timeline-editor'
import { clipColorByIndex } from '@/components/timeline-editor'
import { getClipTrimForSlot } from './clipTrim'
import type { Segment } from './types'

const MIN_SEG = 0.08
const PLACEHOLDER_DUR = 0.5

export type SegmentClipLayout = {
  /** `${segmentId}::${slotIndex}`，占位块 slotIndex 为 -1 */
  blockId: string
  segmentId: string
  segIdx: number
  slotIndex: number
  clipId: string
  timelineStart: number
  timelineEnd: number
  duration: number
  sourceStart: number
  sourceEnd: number
  label: string
  subtitleText: string
  placeholder: boolean
}

export function parseBlockId(blockId: string): { segmentId: string; slotIndex: number } {
  const idx = blockId.lastIndexOf('::')
  if (idx < 0) return { segmentId: blockId, slotIndex: 0 }
  return {
    segmentId: blockId.slice(0, idx),
    slotIndex: Number.parseInt(blockId.slice(idx + 2), 10),
  }
}

export function getOrderedClipIds(seg: Segment): string[] {
  const ids = (seg.selectedClipIds ?? []).filter(Boolean)
  if (ids.length) return ids
  const c = seg.clips[seg.chosenIdx]
  return c?.clip_id ? [c.clip_id] : []
}

export function buildSegmentClipLayouts(segments: Segment[]): SegmentClipLayout[] {
  const layouts: SegmentClipLayout[] = []
  let cursor = 0

  for (let segIdx = 0; segIdx < segments.length; segIdx++) {
    const seg = segments[segIdx]
    const clipIds = getOrderedClipIds(seg)
    const subtitleText = seg.text.trim()

    if (clipIds.length === 0) {
      layouts.push({
        blockId: `${seg.id}::-1`,
        segmentId: seg.id,
        segIdx,
        slotIndex: -1,
        clipId: '',
        timelineStart: cursor,
        timelineEnd: cursor + PLACEHOLDER_DUR,
        duration: PLACEHOLDER_DUR,
        sourceStart: 0,
        sourceEnd: PLACEHOLDER_DUR,
        label: `#${segIdx + 1}`,
        subtitleText,
        placeholder: true,
      })
      cursor += PLACEHOLDER_DUR
      continue
    }

    for (let slotIndex = 0; slotIndex < clipIds.length; slotIndex++) {
      const clipId = clipIds[slotIndex]
      const clip = seg.clips.find((c) => c.clip_id === clipId)
      const trim = clip
        ? getClipTrimForSlot(seg, clip, slotIndex)
        : { inSec: 0, outSec: MIN_SEG }
      const dur = Math.max(MIN_SEG, trim.outSec - trim.inSec)
      const slotLabel =
        clipIds.length > 1 ? `#${segIdx + 1}·${slotIndex + 1}` : `#${segIdx + 1}`

      layouts.push({
        blockId: `${seg.id}::${slotIndex}`,
        segmentId: seg.id,
        segIdx,
        slotIndex,
        clipId,
        timelineStart: cursor,
        timelineEnd: cursor + dur,
        duration: dur,
        sourceStart: trim.inSec,
        sourceEnd: trim.outSec,
        label: slotLabel,
        subtitleText,
        placeholder: false,
      })
      cursor += dur
    }
  }

  return layouts
}

function segmentSpanById(layouts: SegmentClipLayout[]): Map<string, { start: number; end: number; text: string; segIdx: number }> {
  const map = new Map<string, { start: number; end: number; text: string; segIdx: number }>()
  for (const l of layouts) {
    const cur = map.get(l.segmentId)
    if (!cur) {
      map.set(l.segmentId, {
        start: l.timelineStart,
        end: l.timelineEnd,
        text: l.subtitleText,
        segIdx: l.segIdx,
      })
    } else {
      cur.end = l.timelineEnd
    }
  }
  return map
}

export function segmentLayoutsToTracks(layouts: SegmentClipLayout[]): {
  tracks: TimelineTrack[]
  totalDuration: number
} {
  const totalDuration = layouts.length ? layouts[layouts.length - 1].timelineEnd : 0.5
  const spanBySeg = segmentSpanById(layouts)

  const videoClips: TimelineClipBlock[] = []
  const audioClips: TimelineClipBlock[] = []
  const subtitleClips: TimelineClipBlock[] = []

  for (const l of layouts) {
    const base = {
      id: l.blockId,
      timelineStart: l.timelineStart,
      timelineEnd: l.timelineEnd,
      sourceStart: l.sourceStart,
      sourceEnd: l.sourceEnd,
      segmentIndex: l.segIdx,
      clipId: l.clipId || undefined,
      excluded: false,
    }
    videoClips.push({
      ...base,
      label: l.placeholder ? `${l.label} 待匹配` : l.label,
      color: l.placeholder
        ? 'bg-slate-700/35 border-slate-600/50 border-dashed'
        : clipColorByIndex(l.segIdx),
    })
    audioClips.push({
      ...base,
      label: l.placeholder ? '—' : '原声',
      color: 'bg-emerald-600/40 border-emerald-500/50',
    })
  }

  for (const [segmentId, span] of spanBySeg) {
    const text = span.text
    const subLabel = text ? text.slice(0, 14) + (text.length > 14 ? '…' : '') : '（无文案）'
    subtitleClips.push({
      id: `${segmentId}::sub`,
      timelineStart: span.start,
      timelineEnd: span.end,
      sourceStart: 0,
      sourceEnd: span.end - span.start,
      segmentIndex: span.segIdx,
      label: subLabel,
      subtitleText: text,
      color: text
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

export function getNextSegmentLayout(
  layouts: SegmentClipLayout[],
  current: SegmentClipLayout,
): SegmentClipLayout | null {
  const idx = layouts.findIndex((l) => l.blockId === current.blockId)
  if (idx < 0 || idx >= layouts.length - 1) return null
  return layouts[idx + 1]
}

export function playheadToSegmentLayout(
  layouts: SegmentClipLayout[],
  playheadSec: number,
): { layout: SegmentClipLayout; sourceTime: number } | null {
  for (const l of layouts) {
    if (playheadSec >= l.timelineStart && playheadSec < l.timelineEnd) {
      if (l.placeholder) return { layout: l, sourceTime: 0 }
      const ratio = (playheadSec - l.timelineStart) / Math.max(l.duration, MIN_SEG)
      const srcSpan = l.sourceEnd - l.sourceStart
      return { layout: l, sourceTime: l.sourceStart + ratio * srcSpan }
    }
  }
  const last = layouts[layouts.length - 1]
  if (last) return { layout: last, sourceTime: last.sourceEnd }
  return null
}

export function getSubtitleAtPlayhead(layouts: SegmentClipLayout[], playheadSec: number): string | null {
  const hit = playheadToSegmentLayout(layouts, playheadSec)
  if (!hit) return null
  const text = hit.layout.subtitleText?.trim()
  return text || null
}

export function applySegmentClipResize(
  segments: Segment[],
  blockId: string,
  sourceStart: number,
  sourceEnd: number,
): Segment[] {
  const { segmentId, slotIndex } = parseBlockId(blockId)
  if (slotIndex < 0) return segments

  return segments.map((seg) => {
    if (seg.id !== segmentId) return seg
    const clipIds = getOrderedClipIds(seg)
    const clipId = clipIds[slotIndex]
    const clip = seg.clips.find((c) => c.clip_id === clipId)
    if (!clip) return seg

    const metaDur = Math.max(MIN_SEG, Number(clip.duration) || MIN_SEG)
    const hi = Math.max(metaDur, sourceEnd, sourceStart + MIN_SEG)
    const inSec = Math.min(Math.max(0, sourceStart), hi - MIN_SEG)
    const outSec = Math.min(Math.max(inSec + MIN_SEG, sourceEnd), hi)

    const slots = [...(seg.clipTrimSlots ?? clipIds.map(() => ({ inSec: 0, outSec: metaDur })))]
    while (slots.length < clipIds.length) {
      const id = clipIds[slots.length]
      const c = seg.clips.find((x) => x.clip_id === id)
      const d = Math.max(MIN_SEG, Number(c?.duration) || MIN_SEG)
      slots.push({ inSec: 0, outSec: d })
    }
    slots[slotIndex] = { inSec, outSec }

    return { ...seg, clipTrimSlots: slots }
  })
}
