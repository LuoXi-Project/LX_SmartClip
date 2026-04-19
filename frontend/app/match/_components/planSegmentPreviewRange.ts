import type { AutoEditSegmentPlanApi } from '@/lib/api'
import type { ClipMeta } from './autoEditTypes'

/**
 * 将方案段上的 start/end 转为「素材视频绝对时间」用于列表与预览。
 * 口播快剪等路径下 start/end 已是绝对轴；旧数据可能为 clip 文件内相对时间（需加 clip.start_time）。
 */
export function planSegmentPreviewAbsRange(
  s: AutoEditSegmentPlanApi,
  cm: ClipMeta | undefined,
  eps = 0.05
): { displayStart: number; displayEnd: number } {
  const hint = s.subtitle?.timing_hint
  const rawStart = Number(hint?.start ?? s.start_time_sec) || 0
  const rawEnd = Number(hint?.end ?? s.end_time_sec) || rawStart

  if (!cm) {
    return { displayStart: rawStart, displayEnd: Math.max(rawStart, rawEnd) }
  }

  const c0 = Number(cm.start_time)
  const c1 = Number(cm.end_time)
  const clipSpan = Math.max(0, c1 - c0)

  if ((s.clip_trims?.length ?? 0) > 0) {
    return { displayStart: rawStart, displayEnd: Math.max(rawStart, rawEnd) }
  }

  const insideClipAbs =
    rawEnd > rawStart + eps && rawStart >= c0 - eps && rawEnd <= c1 + eps
  if (insideClipAbs) {
    return { displayStart: rawStart, displayEnd: rawEnd }
  }

  const looksRelativeToClipFile =
    clipSpan > 0 &&
    rawStart >= -eps &&
    rawEnd <= clipSpan + eps &&
    rawEnd > rawStart + eps &&
    rawStart < c0 - eps

  if (looksRelativeToClipFile) {
    let mappedStart = rawStart
    const windowDur = rawEnd - rawStart
    if (rawEnd <= clipSpan + eps) {
      mappedStart = rawStart
    } else if (windowDur > 0) {
      mappedStart = 0
    } else {
      mappedStart = Math.min(rawStart, Math.max(0, clipSpan - windowDur))
    }
    mappedStart = Math.max(0, Math.min(mappedStart, Math.max(0, clipSpan - windowDur)))
    const mappedEnd = mappedStart + windowDur
    return { displayStart: c0 + mappedStart, displayEnd: c0 + mappedEnd }
  }

  return { displayStart: rawStart, displayEnd: Math.max(rawStart, rawEnd) }
}
