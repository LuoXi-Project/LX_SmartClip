import type { TimelineClipBlock, TimelineTrack } from '@/components/timeline-editor'
import { clipColorByIndex } from '@/components/timeline-editor'
import type { Segment } from './types'

const MIN_SEG = 0.08

export function clampAudioRange(
  start: number,
  end: number,
  totalDuration: number,
): { start: number; end: number } {
  const dur = Math.max(MIN_SEG, totalDuration)
  let s = Math.max(0, start)
  let e = Math.max(s + MIN_SEG, end)
  s = Math.min(s, dur - MIN_SEG)
  e = Math.min(e, dur)
  if (e <= s) e = Math.min(dur, s + MIN_SEG)
  return { start: s, end: e }
}

export function segmentsToSourceTimelineTracks(
  segments: Segment[],
  totalDuration: number,
): { tracks: TimelineTrack[]; totalDuration: number } {
  const dur = Math.max(totalDuration, MIN_SEG, ...segments.map((s) => s.audioEndSec ?? 0))

  const segmentClips: TimelineClipBlock[] = []
  const audioClips: TimelineClipBlock[] = []
  const subtitleClips: TimelineClipBlock[] = []

  segments.forEach((s, i) => {
    const start = s.audioStartSec ?? 0
    const end = s.audioEndSec ?? start + MIN_SEG
    const base = {
      id: s.id,
      timelineStart: start,
      timelineEnd: end,
      sourceStart: start,
      sourceEnd: end,
      segmentIndex: i,
    }
    const label = `#${i + 1}`
    segmentClips.push({ ...base, label, color: clipColorByIndex(i) })
    audioClips.push({
      ...base,
      label: '原声',
      color: 'bg-rose-600/40 border-rose-500/50',
    })
    const text = s.text.trim()
    const subLabel = text
      ? text.slice(0, 16) + (text.length > 16 ? '…' : '')
      : '（无文案）'
    subtitleClips.push({
      ...base,
      label: subLabel,
      subtitleText: text,
      color: text
        ? 'bg-amber-500/45 border-amber-400/55'
        : 'bg-slate-700/40 border-slate-600/50',
    })
  })

  return {
    totalDuration: dur,
    tracks: [
      { id: 'segment', kind: 'video', label: '段落', clips: segmentClips },
      { id: 'audio', kind: 'audio', label: '底音频', clips: audioClips },
      { id: 'subtitle', kind: 'subtitle', label: '文案', clips: subtitleClips },
    ],
  }
}

export function applyAudioMatchTimelineEdit(
  segments: Segment[],
  segId: string,
  sourceStart: number,
  sourceEnd: number,
  totalDuration: number,
): Segment[] {
  const { start, end } = clampAudioRange(sourceStart, sourceEnd, totalDuration)
  return segments.map((s) =>
    s.id === segId ? { ...s, audioStartSec: start, audioEndSec: end, ttsFilename: null, ttsError: '' } : s,
  )
}

export function getSegmentAtSourceTime(
  segments: Segment[],
  sec: number,
): Segment | null {
  for (const s of segments) {
    const a0 = s.audioStartSec ?? 0
    const a1 = s.audioEndSec ?? a0
    if (sec >= a0 && sec < a1) return s
  }
  return segments.length ? segments[segments.length - 1] : null
}
