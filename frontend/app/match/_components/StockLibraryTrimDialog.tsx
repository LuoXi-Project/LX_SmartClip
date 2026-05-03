'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, RotateCcw, X } from 'lucide-react'
import type { Video } from '@/lib/api'
import { fmt, type ClipTrimRange, videoStreamUrl } from './types'
import { defaultLibraryTrimForVideo } from './clipTrim'

const MIN_SPAN = 0.08
/** 元数据未知时与 defaultLibraryTrimForVideo 一致，避免占位 dur=0.08s 把出点钳死导致一播放就触发「到出点」暂停 */
const PLACEHOLDER_DUR_SEC = 120
const TRIM_PREVIEW_OUT_EDGE = 0.02
const TRIM_PREVIEW_CROSS_MIN_LEFT = 0.07
const PLAYBACK_RATES = [0.25, 0.5, 1, 1.25, 1.5, 2] as const

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n))
}

/** 文案素材成片 · 本地素材库选用顺序下的出入点（与手动匹配 ClipInOutDialog 交互对齐） */
export function StockLibraryTrimDialog({
  open,
  onClose,
  videoIdsOrdered,
  videos,
  initialSlots,
  onSave,
}: {
  open: boolean
  videoIdsOrdered: string[]
  videos: Video[]
  initialSlots: ClipTrimRange[]
  onSave: (slots: ClipTrimRange[]) => void
  onClose: () => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const lastVideoTimeRef = useRef(0)
  const [localSlotTrims, setLocalSlotTrims] = useState<ClipTrimRange[]>([])
  const [activeSlotIndex, setActiveSlotIndex] = useState(0)
  const [dur, setDur] = useState(MIN_SPAN)
  const [inSec, setInSec] = useState(0)
  const [outSec, setOutSec] = useState(MIN_SPAN)
  const [playing, setPlaying] = useState(false)
  const [playbackRate, setPlaybackRate] = useState(1)

  const orderedVideos = useMemo(() => {
    const list: Video[] = []
    for (const id of videoIdsOrdered) {
      const v = videos.find((x) => x.id === id)
      if (v) list.push(v)
    }
    return list
  }, [videoIdsOrdered, videos])

  const activeVideo = useMemo(
    () => orderedVideos[activeSlotIndex] ?? null,
    [orderedVideos, activeSlotIndex],
  )

  const resetFromProps = useCallback(() => {
    if (!orderedVideos.length) return
    const arr = videoIdsOrdered.map((id, i) => initialSlots[i] ?? defaultLibraryTrimForVideo(videos, id))
    setLocalSlotTrims(arr)
    setActiveSlotIndex(0)
    const t0 = arr[0]
    const d0 = Math.max(MIN_SPAN, Number(orderedVideos[0].duration) || PLACEHOLDER_DUR_SEC)
    setDur(d0)
    setInSec(clamp(t0.inSec, 0, d0 - MIN_SPAN))
    setOutSec(clamp(t0.outSec, t0.inSec + MIN_SPAN, d0))
  }, [orderedVideos, videoIdsOrdered, initialSlots, videos])

  useEffect(() => {
    if (open && orderedVideos.length) resetFromProps()
  }, [open, orderedVideos.length, resetFromProps])

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
  }, [playbackRate, activeSlotIndex, activeVideo?.id, open])

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  const switchToSlot = (newIdx: number) => {
    if (newIdx === activeSlotIndex || !orderedVideos.length) return
    const curVid = orderedVideos[activeSlotIndex]
    if (!curVid) return
    const dPrev = Math.max(MIN_SPAN, Number(curVid.duration) || PLACEHOLDER_DUR_SEC)
    const ins = clamp(inSec, 0, dPrev - MIN_SPAN)
    const out = clamp(outSec, ins + MIN_SPAN, dPrev)
    const merged = [...localSlotTrims]
    while (merged.length < orderedVideos.length) merged.push({ inSec: 0, outSec: MIN_SPAN })
    merged[activeSlotIndex] = { inSec: ins, outSec: out }
    setLocalSlotTrims(merged)
    setActiveSlotIndex(newIdx)
    const nv = orderedVideos[newIdx]
    if (!nv) return
    const d = Math.max(MIN_SPAN, Number(nv.duration) || PLACEHOLDER_DUR_SEC)
    setDur(d)
    const t = merged[newIdx] ?? defaultLibraryTrimForVideo(videos, nv.id)
    setInSec(clamp(t.inSec, 0, d - MIN_SPAN))
    setOutSec(clamp(t.outSec, t.inSec + MIN_SPAN, d))
    videoRef.current?.pause()
    setPlaying(false)
  }

  const onLoadedMeta = () => {
    const v = videoRef.current
    if (!v || !Number.isFinite(v.duration) || v.duration <= 0 || !activeVideo) return
    v.playbackRate = playbackRate
    const vd = v.duration
    setDur(vd)
    // 入/出点联动钳位：禁止仅用 clamp(prev, MIN_SPAN, vd)，否则在占位 dur 过小时出点会卡在 ~MIN_SPAN，预览循环会认为「一开始就在出点」而立刻暂停
    setInSec((prevIn) => {
      const ins = clamp(prevIn, 0, vd - MIN_SPAN)
      setOutSec((prevOut) => clamp(prevOut, ins + MIN_SPAN, vd))
      return ins
    })
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

  const playFromIn = () => {
    const v = videoRef.current
    if (!v) return
    seek(inSec)
    void v.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
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
  }, [open, activeSlotIndex, activeVideo?.id])

  useEffect(() => {
    const v = videoRef.current
    if (!v || !open) return

    const syncLast = () => {
      lastVideoTimeRef.current = v.currentTime
    }
    syncLast()

    const tick = () => {
      const t = v.currentTime
      const prev = lastVideoTimeRef.current

      const reachedOut = t >= outSec - TRIM_PREVIEW_OUT_EDGE
      const cameFromLeft = prev < outSec - TRIM_PREVIEW_CROSS_MIN_LEFT
      if (!v.paused && cameFromLeft && reachedOut) {
        v.pause()
        v.currentTime = inSec
        lastVideoTimeRef.current = inSec
        setPlaying(false)
        return
      }

      if (t > outSec + TRIM_PREVIEW_OUT_EDGE) {
        lastVideoTimeRef.current = t
        return
      }

      lastVideoTimeRef.current = t
    }

    v.addEventListener('timeupdate', tick)
    v.addEventListener('seeked', syncLast)
    return () => {
      v.removeEventListener('timeupdate', tick)
      v.removeEventListener('seeked', syncLast)
    }
  }, [open, inSec, outSec, activeSlotIndex, activeVideo?.id])

  const setInFromPlayhead = () => {
    const v = videoRef.current
    if (!v) return
    const t = clamp(v.currentTime, 0, outSec - MIN_SPAN)
    setInSec(t)
    setLocalSlotTrims((prev) => {
      const n = [...prev]
      n[activeSlotIndex] = { inSec: t, outSec }
      return n
    })
  }

  const setOutFromPlayhead = () => {
    const v = videoRef.current
    if (!v) return
    const t = clamp(v.currentTime, inSec + MIN_SPAN, dur)
    setOutSec(t)
    setLocalSlotTrims((prev) => {
      const n = [...prev]
      n[activeSlotIndex] = { inSec, outSec: t }
      return n
    })
  }

  const onInSlider = (x: number) => {
    const nextIn = clamp(x, 0, outSec - MIN_SPAN)
    setInSec(nextIn)
    seek(nextIn)
    setLocalSlotTrims((prev) => {
      const n = [...prev]
      n[activeSlotIndex] = { inSec: nextIn, outSec }
      return n
    })
  }

  const onOutSlider = (x: number) => {
    const nextOut = clamp(x, inSec + MIN_SPAN, dur)
    setOutSec(nextOut)
    seek(nextOut)
    setLocalSlotTrims((prev) => {
      const n = [...prev]
      n[activeSlotIndex] = { inSec, outSec: nextOut }
      return n
    })
  }

  const resetFull = () => {
    if (!activeVideo) return
    const d = Math.max(MIN_SPAN, Number(activeVideo.duration) || dur)
    setInSec(0)
    setOutSec(d)
    setLocalSlotTrims((prev) => {
      const n = [...prev]
      n[activeSlotIndex] = { inSec: 0, outSec: d }
      return n
    })
    seek(0)
  }

  const apply = () => {
    if (!activeVideo || orderedVideos.length === 0) return
    const d = Math.max(MIN_SPAN, Number(activeVideo.duration) || dur)
    const ins = clamp(inSec, 0, d - MIN_SPAN)
    const out = clamp(outSec, ins + MIN_SPAN, d)
    const merged: ClipTrimRange[] = []
    for (let i = 0; i < orderedVideos.length; i++) {
      if (i === activeSlotIndex) merged.push({ inSec: ins, outSec: out })
      else {
        const id = videoIdsOrdered[i]
        merged.push(
          localSlotTrims[i] ?? defaultLibraryTrimForVideo(videos, id),
        )
      }
    }
    onSave(merged)
    onClose()
  }

  if (!open || !orderedVideos.length || !activeVideo) return null

  const span = Math.max(0, outSec - inSec)
  const trackPct = (t: number) => `${(clamp(t / dur, 0, 1) * 100).toFixed(2)}%`

  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center p-3 sm:p-6" aria-modal="true" role="dialog">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-3xl max-h-[min(92vh,900px)] flex flex-col rounded-2xl border border-slate-700/80 bg-[#12141c] shadow-2xl shadow-black/50 overflow-hidden">
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-800 bg-slate-900/50">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-100 truncate">素材库选用区间</p>
            <p className="text-[11px] text-slate-500 truncate">
              与手动匹配出入点一致：按选用顺序切换，合成时将按此区间截取画面
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 p-2 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            aria-label="关闭"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-4 pt-3 flex flex-wrap gap-1.5 border-b border-slate-800/80 pb-3 bg-slate-900/30">
          {orderedVideos.map((v, idx) => {
            const id = videoIdsOrdered[idx]
            const t =
              localSlotTrims[idx] ??
              initialSlots[idx] ??
              defaultLibraryTrimForVideo(videos, id)
            const cd = Math.max(MIN_SPAN, Number(v.duration) || PLACEHOLDER_DUR_SEC)
            const custom = t.inSec > 0.03 || t.outSec < cd - 0.03
            const isActive = idx === activeSlotIndex
            const label = v.name.split(/[/\\]/).pop() ?? v.name
            return (
              <button
                key={`lib-slot-${idx}-${id}`}
                type="button"
                onClick={() => switchToSlot(idx)}
                className={`px-2.5 py-1 rounded-lg text-[11px] border transition-colors max-w-[11rem] truncate ${
                  isActive
                    ? 'bg-indigo-600/30 border-indigo-500/60 text-indigo-100'
                    : 'bg-slate-800/50 border-slate-600 text-slate-400 hover:border-slate-500'
                }`}
                title={v.name}
              >
                <span className="tabular-nums opacity-80 mr-1">{idx + 1}.</span>
                {label}
                {custom ? <span className="ml-1 text-amber-400/90">裁</span> : null}
              </button>
            )
          })}
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <div className="relative rounded-xl overflow-hidden bg-black border border-slate-800 aspect-video">
            <video
              ref={videoRef}
              key={`${activeSlotIndex}-${activeVideo.id}`}
              className="w-full h-full object-contain"
              src={videoStreamUrl(activeVideo.id)}
              preload="metadata"
              playsInline
              controls
              onLoadedMetadata={onLoadedMeta}
              onClick={togglePlay}
            />
            <div className="absolute top-2 left-2 right-2 flex items-center justify-start gap-2 pointer-events-none">
              <span className="text-[10px] px-2 py-1 rounded-md bg-black/65 text-slate-200 tabular-nums">
                选用 {span.toFixed(2)}s / 画面 {dur.toFixed(2)}s
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
            <button
              type="button"
              onClick={playFromIn}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/35 text-xs text-amber-100 hover:bg-amber-500/20"
              title="跳到当前入点并从该处播放"
            >
              <Play className="w-3.5 h-3.5" />
              从入点播放
            </button>
            <div className="flex items-center gap-1 flex-wrap">
              <span className="text-[10px] text-slate-500 shrink-0 mr-0.5">倍速</span>
              {PLAYBACK_RATES.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => {
                    setPlaybackRate(r)
                    const el = videoRef.current
                    if (el) el.playbackRate = r
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
              整段素材
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
                  max={Math.max(0, dur - MIN_SPAN)}
                  step={0.02}
                  value={clamp(inSec, 0, dur - MIN_SPAN)}
                  onChange={(e) => onInSlider(Number(e.target.value))}
                  className="w-full accent-amber-500"
                />
              </label>
              <label className="block text-[11px] text-slate-500 space-y-1">
                <span className="text-cyan-200/90">出点 {fmt(outSec)}</span>
                <input
                  type="range"
                  min={MIN_SPAN}
                  max={dur}
                  step={0.02}
                  value={clamp(outSec, MIN_SPAN, dur)}
                  onChange={(e) => onOutSlider(Number(e.target.value))}
                  className="w-full accent-cyan-500"
                />
              </label>
            </div>
          </div>

          <p className="text-[11px] text-slate-600 leading-relaxed">
            多条素材按序号拼接；点击「应用」保存<strong className="text-slate-400">全部</strong>槽位的区间。
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
