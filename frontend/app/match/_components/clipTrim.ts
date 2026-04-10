import type { MatchClip, SubtitleClipTrimPart } from '@/lib/api'
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

export function trimIsCustom(seg: Segment, clip: MatchClip): boolean {
  const t = getClipTrim(seg, clip)
  const dur = Math.max(0.08, Number(clip.duration) || 0.08)
  return t.inSec > EPS || t.outSec < dur - EPS
}

/**
 * 按 clip_ids 顺序生成 API 的 clip_trims（与 burn 拼接顺序一致）。
 */
export function buildClipTrimsForApi(seg: Segment, clipIdsOrdered: string[]): SubtitleClipTrimPart[] {
  const out: SubtitleClipTrimPart[] = []
  for (const id of clipIdsOrdered) {
    const clip = seg.clips.find((c) => c.clip_id === id)
    if (!clip) continue
    const t = getClipTrim(seg, clip)
    const span = Math.max(0.08, t.outSec - t.inSec)
    out.push({
      clip_id: id,
      clip_start_sec: t.inSec,
      duration_sec: span,
    })
  }
  return out
}
