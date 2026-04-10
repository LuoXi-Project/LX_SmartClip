'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, RotateCcw, X } from 'lucide-react'
import type { MatchClip } from '@/lib/api'
import { clipStreamUrl, fmt, type ClipTrimRange, type Segment } from './types'
import { getClipTrim } from './clipTrim'

const MIN_SPAN = 0.08
const TRIM_BADGE_EPS = 0.03
/** 预览倍速（仅影响弹窗内播放，不改变导出） */
const PLAYBACK_RATES = [0.25, 0.5, 1, 1.25, 1.5, 2] as const

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n))
}

export function ClipInOutDialog({
  open,
  segment,
  onClose,
  onSave,
}: {
  open: boolean
  segment: Segment | null
  onClose: () => void
  /** 写入段落 clipTrimByClipId（仅包含当前勾选素材的 id） */
  onSave: (trims: Record<string, ClipTrimRange>) => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [localTrims, setLocalTrims] = useState<Record<string, ClipTrimRange>>({})
  const [activeId, setActiveId] = useState<string>('')
  const [dur, setDur] = useState(MIN_SPAN)
  const [inSec, setInSec] = useState(0)
  const [outSec, setOutSec] = useState(MIN_SPAN)
  const [playing, setPlaying] = useState(false)
  const [playbackRate, setPlaybackRate] = useState(1)

  const orderedClips = useMemo(() => {
    if (!segment?.selectedClipIds?.length) return [] as MatchClip[]
    const list: MatchClip[] = []
    for (const id of segment.selectedClipIds) {
      const c = segment.clips.find((x) => x.clip_id === id)
      if (c) list.push(c)
    }
    return list
  }, [segment])

  const activeClip = useMemo(
    () => orderedClips.find((c) => c.clip_id === activeId) ?? null,
    [orderedClips, activeId],
  )

  const resetFromSegment = useCallback(() => {
    if (!segment || !orderedClips.length) return
    const next: Record<string, ClipTrimRange> = {}
    for (const c of orderedClips) {
      next[c.clip_id] = getClipTrim(segment, c)
    }
    setLocalTrims(next)
    const firstId = orderedClips[0].clip_id
    setActiveId(firstId)
    const t0 = next[firstId] ?? { inSec: 0, outSec: orderedClips[0].duration }
    setInSec(t0.inSec)
    setOutSec(t0.outSec)
    const d0 = Math.max(MIN_SPAN, Number(orderedClips[0].duration) || MIN_SPAN)
    setDur(d0)
  }, [segment, orderedClips])

  useEffect(() => {
    if (open && segment && orderedClips.length) resetFromSegment()
  }, [open, segment?.id, segment?.selectedClipIds?.join(','), resetFromSegment, orderedClips.length])

  useEffect(() => {
    if (!open) {
      setPlaying(false)
      setPlaybackRate(1)
      videoRef.current?.pause()
    }
  }, [open])

  useEffect(() => {
    const v = videoRef.current
    if (!v || !open) return
    v.playbackRate = playbackRate
  }, [playbackRate, activeClip?.clip_id, open])

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  const switchToClip = (cid: string) => {
    if (cid === activeId || !activeClip || !segment) return
    const dPrev = Math.max(MIN_SPAN, Number(activeClip.duration) || MIN_SPAN)
    const ins = clamp(inSec, 0, dPrev - MIN_SPAN)
    const out = clamp(outSec, ins + MIN_SPAN, dPrev)
    const updated = { ...localTrims, [activeId]: { inSec: ins, outSec: out } }
    setLocalTrims(updated)
    setActiveId(cid)
    const clip = orderedClips.find((c) => c.clip_id === cid)
    if (!clip) return
    const d = Math.max(MIN_SPAN, Number(clip.duration) || MIN_SPAN)
    setDur(d)
    const t = updated[cid] ?? getClipTrim(segment, clip)
    setInSec(clamp(t.inSec, 0, d - MIN_SPAN))
    setOutSec(clamp(t.outSec, t.inSec + MIN_SPAN, d))
    videoRef.current?.pause()
    setPlaying(false)
  }

  const onLoadedMeta = () => {
    const v = videoRef.current
    if (!v || !Number.isFinite(v.duration) || v.duration <= 0 || !activeClip) return
    v.playbackRate = playbackRate
    const vd = v.duration
    setDur(vd)
    setInSec((prev) => clamp(prev, 0, vd - MIN_SPAN))
    setOutSec((prev) => clamp(prev, MIN_SPAN, vd))
  }

  const seek = (t: number) => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = clamp(t, 0, Math.max(0, dur - 0.001))
  }

  const togglePlay = () => {
    const v = videoRef.current
    if (!v) return
    if (playing) {
      v.pause()
      setPlaying(false)
    } else {
      void v.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
    }
  }

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const onPause = () => setPlaying(false)
    const onPlay = () => setPlaying(true)
    v.addEventListener('pause', onPause)
    v.addEventListener('play', onPlay)
    return () => {
      v.removeEventListener('pause', onPause)
      v.removeEventListener('play', onPlay)
    }
  }, [open, activeClip?.clip_id])

  useEffect(() => {
    const v = videoRef.current
    if (!v || !open) return
    const tick = () => {
      if (v.currentTime >= outSec - 0.02) {
        v.pause()
        v.currentTime = inSec
        setPlaying(false)
      }
    }
    v.addEventListener('timeupdate', tick)
    return () => v.removeEventListener('timeupdate', tick)
  }, [open, inSec, outSec])

  const setInFromPlayhead = () => {
    const v = videoRef.current
    if (!v) return
    const t = clamp(v.currentTime, 0, outSec - MIN_SPAN)
    setInSec(t)
    setLocalTrims((prev) => ({ ...prev, [activeId]: { inSec: t, outSec } }))
  }

  const setOutFromPlayhead = () => {
    const v = videoRef.current
    if (!v) return
    const t = clamp(v.currentTime, inSec + MIN_SPAN, dur)
    setOutSec(t)
    setLocalTrims((prev) => ({ ...prev, [activeId]: { inSec, outSec: t } }))
  }

  const onInSlider = (v: number) => {
    setInSec(v)
    seek(v)
    setLocalTrims((prev) => ({ ...prev, [activeId]: { inSec: v, outSec } }))
  }

  const onOutSlider = (v: number) => {
    setOutSec(v)
    seek(v)
    setLocalTrims((prev) => ({ ...prev, [activeId]: { inSec, outSec: v } }))
  }

  const resetFull = () => {
    if (!activeClip) return
    const d = Math.max(MIN_SPAN, Number(activeClip.duration) || MIN_SPAN)
    setInSec(0)
    setOutSec(d)
    setLocalTrims((prev) => ({ ...prev, [activeId]: { inSec: 0, outSec: d } }))
    seek(0)
  }

  const apply = () => {
    if (!activeClip || !activeId) return
    const d = Math.max(MIN_SPAN, Number(activeClip.duration) || MIN_SPAN)
    const ins = clamp(inSec, 0, d - MIN_SPAN)
    const out = clamp(outSec, ins + MIN_SPAN, d)
    const merged = { ...localTrims, [activeId]: { inSec: ins, outSec: out } }
    onSave(merged)
    onClose()
  }

  if (!open || !segment || orderedClips.length === 0 || !activeClip) return null

  const span = Math.max(0, outSec - inSec)
  const trackPct = (t: number) => `${(clamp(t / dur, 0, 1) * 100).toFixed(2)}%`

  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center p-3 sm:p-6" aria-modal="true" role="dialog">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-3xl max-h-[min(92vh,900px)] flex flex-col rounded-2xl border border-slate-700/80 bg-[#12141c] shadow-2xl shadow-black/50 overflow-hidden">
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-800 bg-slate-900/50">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-100 truncate">片段出入点</p>
            <p className="text-[11px] text-slate-500 truncate">
              下方切换已勾选素材，分别设置入点/出点；导出时按勾选顺序拼接并应用各段裁剪
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 p-2 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            aria-label="关闭"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 pt-3 flex flex-wrap gap-1.5 border-b border-slate-800/80 pb-3 bg-slate-900/30">
          {orderedClips.map((c, idx) => {
            const t = localTrims[c.clip_id] ?? (segment ? getClipTrim(segment, c) : { inSec: 0, outSec: c.duration })
            const cd = Math.max(MIN_SPAN, Number(c.duration) || MIN_SPAN)
            const custom = t.inSec > TRIM_BADGE_EPS || t.outSec < cd - TRIM_BADGE_EPS
            const isActive = c.clip_id === activeId
            return (
              <button
                key={c.clip_id}
                type="button"
                onClick={() => switchToClip(c.clip_id)}
                className={`px-2.5 py-1 rounded-lg text-[11px] border transition-colors ${
                  isActive
                    ? 'bg-indigo-600/30 border-indigo-500/60 text-indigo-100'
                    : 'bg-slate-800/50 border-slate-600 text-slate-400 hover:border-slate-500'
                }`}
              >
                <span className="tabular-nums opacity-80 mr-1">{idx + 1}.</span>
                <span className="font-mono truncate max-w-[7rem] sm:max-w-[10rem] align-bottom inline-block">
                  {c.clip_id}
                </span>
                {custom ? <span className="ml-1 text-amber-400/90">裁</span> : null}
              </button>
            )
          })}
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <div className="relative rounded-xl overflow-hidden bg-black border border-slate-800 aspect-video">
            <video
              ref={videoRef}
              key={activeClip.clip_id}
              className="w-full h-full object-contain"
              src={clipStreamUrl(activeClip.clip_id)}
              preload="metadata"
              playsInline
              onLoadedMetadata={onLoadedMeta}
              onClick={togglePlay}
            />
            <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between gap-2 pointer-events-none">
              <span className="text-[10px] px-2 py-1 rounded-md bg-black/65 text-slate-200 tabular-nums">
                本段选用 {span.toFixed(2)}s / 文件 {dur.toFixed(2)}s
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={togglePlay}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-600 text-xs text-slate-200 hover:bg-slate-700"
            >
              {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
              {playing ? '暂停' : '播放'}
            </button>
            <div className="flex items-center gap-1 flex-wrap">
              <span className="text-[10px] text-slate-500 shrink-0 mr-0.5">倍速</span>
              {PLAYBACK_RATES.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => {
                    setPlaybackRate(r)
                    const v = videoRef.current
                    if (v) v.playbackRate = r
                  }}
                  className={`min-w-[2.25rem] px-1.5 py-1 rounded-md text-[11px] tabular-nums border transition-colors ${
                    playbackRate === r
                      ? 'bg-violet-600/35 border-violet-500/60 text-violet-100'
                      : 'bg-slate-800/80 border-slate-600 text-slate-400 hover:border-slate-500 hover:text-slate-200'
                  }`}
                >
                  {r === 1 ? '1×' : `${r}×`}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={setInFromPlayhead}
              className="px-3 py-1.5 rounded-lg bg-amber-500/15 border border-amber-500/40 text-xs text-amber-200 hover:bg-amber-500/25"
            >
              入点 ← 当前位置
            </button>
            <button
              type="button"
              onClick={setOutFromPlayhead}
              className="px-3 py-1.5 rounded-lg bg-cyan-500/15 border border-cyan-500/40 text-xs text-cyan-200 hover:bg-cyan-500/25"
            >
              出点 ← 当前位置
            </button>
            <button
              type="button"
              onClick={resetFull}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-600 text-xs text-slate-400 hover:bg-slate-800"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              本素材整段
            </button>
          </div>

          <div className="space-y-2">
            <div className="relative h-9 rounded-lg bg-slate-900 border border-slate-700 overflow-hidden">
              <div className="absolute inset-y-0 left-0 bg-slate-800/80" style={{ width: trackPct(inSec) }} />
              <div
                className="absolute inset-y-0 bg-indigo-500/35 border-x-2 border-indigo-400/90"
                style={{ left: trackPct(inSec), width: `calc(${trackPct(outSec)} - ${trackPct(inSec)})` }}
              />
              <div className="absolute inset-y-0 right-0 bg-slate-800/80" style={{ left: trackPct(outSec), right: 0 }} />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="block text-[11px] text-slate-500 space-y-1">
                <span className="text-amber-200/90">入点 {fmt(inSec)}</span>
                <input
                  type="range"
                  min={0}
                  max={Math.max(0, outSec - MIN_SPAN)}
                  step={0.02}
                  value={clamp(inSec, 0, outSec - MIN_SPAN)}
                  onChange={(e) => onInSlider(Number(e.target.value))}
                  className="w-full accent-amber-500"
                />
              </label>
              <label className="block text-[11px] text-slate-500 space-y-1">
                <span className="text-cyan-200/90">出点 {fmt(outSec)}</span>
                <input
                  type="range"
                  min={inSec + MIN_SPAN}
                  max={dur}
                  step={0.02}
                  value={clamp(outSec, inSec + MIN_SPAN, dur)}
                  onChange={(e) => onOutSlider(Number(e.target.value))}
                  className="w-full accent-cyan-500"
                />
              </label>
            </div>
          </div>

          <p className="text-[11px] text-slate-600 leading-relaxed">
            勾选多个素材时，成片按序号顺序拼接；每一段可单独裁剪。点击「应用」会保存<strong className="text-slate-400">所有</strong>已选素材的当前设置。
          </p>
        </div>

        <div className="flex justify-end gap-2 px-4 py-3 border-t border-slate-800 bg-slate-900/40">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-sm text-slate-400 hover:bg-slate-800"
          >
            取消
          </button>
          <button
            type="button"
            onClick={apply}
            className="px-4 py-2 rounded-xl text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white"
          >
            应用
          </button>
        </div>
      </div>
    </div>
  )
}
