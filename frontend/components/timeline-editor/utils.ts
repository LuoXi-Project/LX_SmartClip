export function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n))
}

export function fmtTime(s: number) {
  const totalMs = Math.max(0, Math.round((Number.isFinite(s) ? s : 0) * 1000))
  const m = Math.floor(totalMs / 60000)
  const sec = Math.floor((totalMs % 60000) / 1000)
  const ms = totalMs % 1000
  if (m > 0) {
    return `${m}:${sec.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`
  }
  return `${sec}.${ms.toString().padStart(3, '0')}s`
}

export function fmtTimeShort(s: number) {
  const t = Math.max(0, Number.isFinite(s) ? s : 0)
  if (t >= 60) return fmtTime(t)
  return `${t.toFixed(1)}s`
}

/** 根据总时长选择合适的刻度间隔（秒） */
export function pickTickStep(_totalSec: number, pxPerSec: number) {
  const targetPx = 72
  const rough = targetPx / Math.max(pxPerSec, 1)
  const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300]
  for (const s of steps) {
    if (s >= rough) return s
  }
  return steps[steps.length - 1]
}

export function buildRulerTicks(totalSec: number, step: number) {
  const ticks: number[] = []
  const n = Math.ceil(totalSec / step) + 1
  for (let i = 0; i <= n; i++) {
    const t = i * step
    if (t <= totalSec + step * 0.01) ticks.push(t)
  }
  return ticks
}

const CLIP_COLORS = [
  'bg-violet-500/55 border-violet-400/70',
  'bg-cyan-500/50 border-cyan-400/65',
  'bg-emerald-500/50 border-emerald-400/65',
  'bg-amber-500/50 border-amber-400/65',
  'bg-rose-500/50 border-rose-400/65',
  'bg-indigo-500/50 border-indigo-400/65',
]

export function clipColorByIndex(i: number) {
  return CLIP_COLORS[i % CLIP_COLORS.length]
}
