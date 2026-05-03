import type { MatchClip, SubtitleClipTrimPart, Video } from '@/lib/api'
import type { ClipTrimRange, Segment } from './types'

const EPS = 0.03

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n))
}

/** 解析后的有效区间（秒），保证 out > in */
export function getClipTrim(seg: Segment, clip: MatchClip): ClipTrimRange {
  const metaDur = Math.max(0.08, Number(clip.duration) || 0.08)
  const raw = seg.clipTrimByClipId?.[clip.clip_id]
  if (!raw) return { inSec: 0, outSec: metaDur }
  // 预览以浏览器探测时长为准，可能长于接口里的 duration；勿用元数据把用户已保存的出点压短
  const hi = Math.max(metaDur, Number(raw.outSec) || 0, Number(raw.inSec) + 0.08)
  const ins = clamp(Number(raw.inSec) || 0, 0, hi - 0.08)
  const out = clamp(Number(raw.outSec) || hi, ins + 0.08, hi)
  return { inSec: ins, outSec: out }
}

/** 带选用槽位：优先 clipTrimSlots[slot]，否则回退 clipTrimByClipId */
export function getClipTrimForSlot(seg: Segment, clip: MatchClip, slotIndex: number): ClipTrimRange {
  const metaDur = Math.max(0.08, Number(clip.duration) || 0.08)
  const slot = seg.clipTrimSlots?.[slotIndex]
  if (slot && typeof slot.inSec === 'number' && typeof slot.outSec === 'number') {
    const hi = Math.max(metaDur, Number(slot.outSec) || 0, Number(slot.inSec) + 0.08)
    const ins = clamp(Number(slot.inSec) || 0, 0, hi - 0.08)
    const out = clamp(Number(slot.outSec) || hi, ins + 0.08, hi)
    return { inSec: ins, outSec: out }
  }
  return getClipTrim(seg, clip)
}

export function defaultTrimForClipId(seg: Segment, clipId: string): ClipTrimRange {
  const clip = seg.clips.find((c) => c.clip_id === clipId)
  if (!clip) return { inSec: 0, outSec: 0.08 }
  return getClipTrim(seg, clip)
}

/**
 * 勾选顺序变化时，按「顺序贪心」保留原有槽位裁剪：同名 clip 按序消耗上一轮的条目，新增的槽用默认裁剪。
 */
export function computeNextTrimSlots(
  seg: Segment,
  prevIds: string[],
  prevSlots: ClipTrimRange[] | undefined,
  nextIds: string[],
): ClipTrimRange[] | undefined {
  if (nextIds.length === 0) return undefined
  const prevPairs = prevIds.map((id, i) => ({
    id,
    trim: prevSlots?.[i] ?? defaultTrimForClipId(seg, id),
  }))
  const used = new Set<number>()
  const result: ClipTrimRange[] = []
  for (const nid of nextIds) {
    let found = -1
    for (let j = 0; j < prevPairs.length; j++) {
      if (used.has(j)) continue
      if (prevPairs[j].id === nid) {
        found = j
        break
      }
    }
    if (found >= 0) {
      used.add(found)
      result.push(prevPairs[found].trim)
    } else {
      result.push(defaultTrimForClipId(seg, nid))
    }
  }
  return result
}

export function trimIsCustom(seg: Segment, clip: MatchClip): boolean {
  const t = getClipTrim(seg, clip)
  const dur = Math.max(0.08, Number(clip.duration) || 0.08)
  return t.inSec > EPS || t.outSec < dur - EPS
}

export function trimIsCustomForSlot(seg: Segment, clip: MatchClip, slotIndex: number): boolean {
  const t = getClipTrimForSlot(seg, clip, slotIndex)
  const dur = Math.max(0.08, Number(clip.duration) || 0.08)
  return t.inSec > EPS || t.outSec < dur - EPS
}

/**
 * 按 clip_ids 顺序生成 API 的 clip_trims（与 burn 拼接顺序一致）。
 */
/** 素材库整段视频默认选用区间（元数据时长；未知时用占位便于滑条） */
export function defaultLibraryTrimForVideo(videos: Video[], videoId: string): ClipTrimRange {
  const v = videos.find((x) => x.id === videoId)
  const d = Number(v?.duration)
  if (!Number.isFinite(d) || d <= 0) return { inSec: 0, outSec: 120 }
  return { inSec: 0, outSec: Math.max(0.08, d) }
}

export function computeNextLibraryTrimSlots(
  prevIds: string[],
  prevSlots: ClipTrimRange[] | undefined,
  nextIds: string[],
  videos: Video[],
): ClipTrimRange[] | undefined {
  if (nextIds.length === 0) return undefined
  const prevPairs = prevIds.map((id, i) => ({
    id,
    trim: prevSlots?.[i] ?? defaultLibraryTrimForVideo(videos, id),
  }))
  const used = new Set<number>()
  const result: ClipTrimRange[] = []
  for (const nid of nextIds) {
    let found = -1
    for (let j = 0; j < prevPairs.length; j++) {
      if (used.has(j)) continue
      if (prevPairs[j].id === nid) {
        found = j
        break
      }
    }
    if (found >= 0) {
      used.add(found)
      result.push(prevPairs[found].trim)
    } else {
      result.push(defaultLibraryTrimForVideo(videos, nid))
    }
  }
  return result
}

/** 是否相对素材库声明时长做过裁剪（无时长元数据时仅以入点判断） */
export function libraryTrimSlotIsCustom(videos: Video[], videoId: string, slot: ClipTrimRange): boolean {
  const v = videos.find((x) => x.id === videoId)
  const dur = Number(v?.duration)
  if (!Number.isFinite(dur) || dur <= 0.08) return slot.inSec > EPS
  return slot.inSec > EPS || slot.outSec < dur - EPS
}

export function buildClipTrimsForApi(seg: Segment, clipIdsOrdered: string[]): SubtitleClipTrimPart[] {
  const out: SubtitleClipTrimPart[] = []
  clipIdsOrdered.forEach((id, slotIndex) => {
    const clip = seg.clips.find((c) => c.clip_id === id)
    if (!clip) return
    const t = getClipTrimForSlot(seg, clip, slotIndex)
    const span = Math.max(0.08, t.outSec - t.inSec)
    out.push({
      clip_id: id,
      clip_start_sec: t.inSec,
      duration_sec: span,
    })
  })
  return out
}
