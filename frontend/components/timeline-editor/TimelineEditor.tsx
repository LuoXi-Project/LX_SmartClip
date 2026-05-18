'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Eye, EyeOff, Volume2, VolumeX, ZoomIn, ZoomOut } from 'lucide-react'
import { TimelineRuler } from './TimelineRuler'
import type { TimelineClipBlock, TimelineEditorProps } from './types'
import { clamp, clipColorByIndex, fmtTime } from './utils'

const LABEL_W = 100
const TRACK_H = 44
const MIN_CLIP_SEC = 0.08
const HANDLE_W = 8
const SNAP_EPS = 0.06

type DragState = {
  kind: 'playhead' | 'resize-start' | 'resize-end' | 'move'
  clipId?: string
  trackId?: string
  startX: number
  originTimelineStart: number
  originTimelineEnd: number
  originSourceStart: number
  originSourceEnd: number
}

type ClipPreview = {
  timelineStart: number
  timelineEnd: number
  sourceStart: number
  sourceEnd: number
}

export function TimelineEditor({
  tracks,
  totalDuration,
  playheadSec,
  onPlayheadChange,
  selection,
  onSelectionChange,
  editable = false,
  onClipResize,
  onClipMove,
  className = '',
  pxPerSec: pxPerSecProp,
  onPxPerSecChange,
  minPxPerSec = 12,
  maxPxPerSec = 120,
  followPlayhead = true,
  onTrimDragChange,
  trackStates,
  onTrackStateChange,
}: TimelineEditorProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [internalPx, setInternalPx] = useState(28)
  const pxPerSec = pxPerSecProp ?? internalPx
  const setPxPerSec = onPxPerSecChange ?? setInternalPx

  const [drag, setDrag] = useState<DragState | null>(null)
  const [clipPreview, setClipPreview] = useState<Record<string, ClipPreview>>({})
  const clipPreviewRef = useRef(clipPreview)
  clipPreviewRef.current = clipPreview
  const [dragHint, setDragHint] = useState<string | null>(null)

  const duration = Math.max(totalDuration, 0.5)
  const contentWidth = Math.max(duration * pxPerSec + 40, 200)
  const playheadLeft = LABEL_W + playheadSec * pxPerSec

  const xToSec = useCallback(
    (clientX: number, el: HTMLElement) => {
      const rect = el.getBoundingClientRect()
      const x = clientX - rect.left + el.scrollLeft - LABEL_W
      return clamp(x / pxPerSec, 0, duration)
    },
    [duration, pxPerSec],
  )

  const snapSec = useCallback(
    (sec: number, excludeClipId?: string) => {
      const candidates = [0, playheadSec, duration]
      for (const track of tracks) {
        for (const c of track.clips) {
          if (c.id === excludeClipId) continue
          candidates.push(c.timelineStart, c.timelineEnd)
        }
      }
      for (const t of candidates) {
        if (Math.abs(sec - t) < SNAP_EPS) return t
      }
      return sec
    },
    [duration, playheadSec, tracks],
  )

  /** 播放头移出可视区时自动滚动画布 */
  useEffect(() => {
    if (!followPlayhead || !scrollRef.current) return
    const el = scrollRef.current
    const margin = 100
    const viewLeft = el.scrollLeft
    const viewRight = viewLeft + el.clientWidth
    if (playheadLeft < viewLeft + margin) {
      el.scrollLeft = Math.max(0, playheadLeft - margin)
    } else if (playheadLeft > viewRight - margin) {
      el.scrollLeft = playheadLeft - el.clientWidth + margin
    }
  }, [followPlayhead, playheadLeft])

  const commitClipChange = useCallback(
    (dragState: DragState, preview: ClipPreview) => {
      if (!dragState.clipId || !dragState.trackId) return
      if (dragState.kind === 'resize-start' || dragState.kind === 'resize-end') {
        onClipResize?.({
          clipId: dragState.clipId,
          trackId: dragState.trackId,
          edge: dragState.kind === 'resize-start' ? 'start' : 'end',
          timelineStart: preview.timelineStart,
          timelineEnd: preview.timelineEnd,
          sourceStart: preview.sourceStart,
          sourceEnd: preview.sourceEnd,
        })
      } else if (dragState.kind === 'move') {
        onClipMove?.({
          clipId: dragState.clipId,
          trackId: dragState.trackId,
          deltaSec: preview.timelineStart - dragState.originTimelineStart,
          timelineStart: preview.timelineStart,
          timelineEnd: preview.timelineEnd,
        })
      }
    },
    [onClipMove, onClipResize],
  )

  const computeResizePreview = (dragState: DragState, dx: number): ClipPreview | null => {
    const srcDur = Math.max(MIN_CLIP_SEC, dragState.originSourceEnd - dragState.originSourceStart)
    const outDur = Math.max(MIN_CLIP_SEC, dragState.originTimelineEnd - dragState.originTimelineStart)

    if (dragState.kind === 'resize-end') {
      const newOutDur = clamp(outDur + dx, MIN_CLIP_SEC, outDur + 120)
      const ratio = newOutDur / outDur
      const newSrcEnd = dragState.originSourceStart + srcDur * ratio
      return {
        timelineStart: dragState.originTimelineStart,
        timelineEnd: dragState.originTimelineStart + newOutDur,
        sourceStart: dragState.originSourceStart,
        sourceEnd: newSrcEnd,
      }
    }
    if (dragState.kind === 'resize-start') {
      const trim = clamp(dx, -(outDur - MIN_CLIP_SEC), outDur - MIN_CLIP_SEC)
      const newOutDur = outDur - trim
      const ratio = newOutDur / outDur
      const srcTrim = srcDur * (1 - ratio)
      return {
        timelineStart: dragState.originTimelineStart + trim,
        timelineEnd: dragState.originTimelineEnd,
        sourceStart: dragState.originSourceStart + srcTrim,
        sourceEnd: dragState.originSourceEnd,
      }
    }
    return null
  }

  useEffect(() => {
    if (!drag) return

    const onMove = (e: PointerEvent) => {
      if (!scrollRef.current) return

      if (drag.kind === 'playhead') {
        const sec = snapSec(xToSec(e.clientX, scrollRef.current))
        onPlayheadChange(sec)
        return
      }

      if (!drag.clipId) return
      const dx = (e.clientX - drag.startX) / pxPerSec
      const preview = computeResizePreview(drag, dx)
      if (!preview) return

      setClipPreview({ [drag.clipId]: preview })
      const edge = drag.kind === 'resize-start' ? preview.sourceStart : preview.sourceEnd
      setDragHint(
        `${drag.kind === 'resize-start' ? '入点' : '出点'} ${fmtTime(edge)} · 时长 ${(preview.timelineEnd - preview.timelineStart).toFixed(2)}s`,
      )
    }

    const onUp = () => {
      const wasTrim = drag.kind === 'resize-start' || drag.kind === 'resize-end'
      const preview = drag.clipId ? clipPreviewRef.current[drag.clipId] : undefined
      if (preview) commitClipChange(drag, preview)
      setDrag(null)
      setClipPreview({})
      setDragHint(null)
      if (wasTrim) onTrimDragChange?.(false)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [commitClipChange, drag, onPlayheadChange, pxPerSec, snapSec, xToSec])

  const onPointerDownPlayhead = (e: React.PointerEvent) => {
    if (!scrollRef.current) return
    e.preventDefault()
    e.stopPropagation()
    const sec = snapSec(xToSec(e.clientX, scrollRef.current))
    onPlayheadChange(sec)
    setDrag({
      kind: 'playhead',
      startX: e.clientX,
      originTimelineStart: sec,
      originTimelineEnd: sec,
      originSourceStart: 0,
      originSourceEnd: 0,
    })
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }

  const onPointerDownClip = (
    e: React.PointerEvent,
    clip: TimelineClipBlock,
    trackId: string,
    edge: 'start' | 'end' | 'move',
  ) => {
    if (!editable) return
    if (clip.excluded && edge !== 'move') return
    e.stopPropagation()
    e.preventDefault()
    // 拖出入点时不要触发选区变更，避免播放头被重置到片段起点
    if (selection?.clipId !== clip.id || selection?.trackId !== trackId) {
      onSelectionChange({ clipId: clip.id, trackId })
    }
    const isTrim = edge === 'start' || edge === 'end'
    if (isTrim) onTrimDragChange?.(true)
    setDrag({
      kind: edge === 'move' ? 'move' : edge === 'start' ? 'resize-start' : 'resize-end',
      clipId: clip.id,
      trackId,
      startX: e.clientX,
      originTimelineStart: clip.timelineStart,
      originTimelineEnd: clip.timelineEnd,
      originSourceStart: clip.sourceStart,
      originSourceEnd: clip.sourceEnd,
    })
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }

  const onTrackAreaClick = (e: React.MouseEvent) => {
    if (drag) return
    if (!scrollRef.current) return
    if ((e.target as HTMLElement).closest('[data-clip-block]')) return
    const sec = snapSec(xToSec(e.clientX, scrollRef.current))
    onPlayheadChange(sec)
  }

  const resolveClip = (clip: TimelineClipBlock) => {
    const p = clipPreview[clip.id]
    if (!p) return clip
    return { ...clip, ...p }
  }

  const trackKindStyle: Record<string, string> = {
    video: 'text-violet-300/90',
    audio: 'text-emerald-300/90',
    subtitle: 'text-amber-300/90',
  }

  const getTrackState = (trackId: string) => trackStates?.[trackId] ?? {}

  const toggleTrackVisible = (trackId: string) => {
    const cur = getTrackState(trackId).visible !== false
    onTrackStateChange?.(trackId, { visible: !cur })
  }

  const toggleTrackMuted = (trackId: string) => {
    const cur = getTrackState(trackId).muted === true
    onTrackStateChange?.(trackId, { muted: !cur })
  }

  const renderTrackControl = (track: (typeof tracks)[0]) => {
    const st = getTrackState(track.id)
    if (track.kind === 'audio') {
      const muted = st.muted === true
      return (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            toggleTrackMuted(track.id)
          }}
          className={`p-0.5 rounded hover:bg-slate-800 ${muted ? 'text-rose-400' : 'text-slate-400'}`}
          title={muted ? '取消静音' : '静音'}
        >
          {muted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
        </button>
      )
    }
    if (track.kind === 'video' || track.kind === 'subtitle') {
      const visible = st.visible !== false
      return (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            toggleTrackVisible(track.id)
          }}
          className={`p-0.5 rounded hover:bg-slate-800 ${visible ? 'text-slate-300' : 'text-slate-600'}`}
          title={
            track.kind === 'video'
              ? visible
                ? '隐藏视频预览'
                : '显示视频预览'
              : visible
                ? '隐藏字幕预览'
                : '显示字幕预览'
          }
        >
          {visible ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
        </button>
      )
    }
    return null
  }

  return (
    <div className={`flex flex-col rounded-xl border border-slate-800 bg-[#0a0c10] overflow-hidden ${className}`}>
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-slate-800/80 bg-slate-950/60">
        <div className="text-[11px] text-slate-500 tabular-nums min-w-0 truncate">
          播放头 <span className="text-red-300">{fmtTime(playheadSec)}</span>
          <span className="mx-2 text-slate-700">/</span>
          总长 <span className="text-slate-400">{fmtTime(duration)}</span>
          {dragHint && <span className="ml-3 text-cyan-400/90">{dragHint}</span>}
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            type="button"
            onClick={() => setPxPerSec(clamp(pxPerSec - 6, minPxPerSec, maxPxPerSec))}
            className="p-1.5 rounded-md border border-slate-700 text-slate-400 hover:bg-slate-800"
            title="缩小"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-[10px] text-slate-600 tabular-nums w-8 text-center">{Math.round(pxPerSec)}</span>
          <button
            type="button"
            onClick={() => setPxPerSec(clamp(pxPerSec + 6, minPxPerSec, maxPxPerSec))}
            className="p-1.5 rounded-md border border-slate-700 text-slate-400 hover:bg-slate-800"
            title="放大"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="overflow-x-auto overflow-y-hidden select-none relative"
        onClick={onTrackAreaClick}
      >
        <div className="relative" style={{ width: contentWidth + LABEL_W, minWidth: '100%' }}>
          <TimelineRuler totalDuration={duration} pxPerSec={pxPerSec} labelWidth={LABEL_W} />

          {tracks.map((track) => {
            const st = getTrackState(track.id)
            const clipsDimmed =
              (track.kind === 'video' && st.visible === false) ||
              (track.kind === 'subtitle' && st.visible === false)
            return (
            <div
              key={track.id}
              className="flex border-b border-slate-800/60 last:border-b-0"
              style={{ height: TRACK_H }}
            >
              <div
                className={`flex-shrink-0 border-r border-slate-800/80 pl-1.5 pr-1 flex items-center gap-0.5 text-[10px] font-medium ${trackKindStyle[track.kind] ?? 'text-slate-400'}`}
                style={{ width: LABEL_W }}
              >
                {renderTrackControl(track)}
                <span className="truncate flex-1 min-w-0">{track.label}</span>
              </div>
              <div
                className={`relative flex-1 bg-slate-950/40 ${clipsDimmed ? 'opacity-35' : ''}`}
                style={{ width: contentWidth }}
              >
                {track.clips.map((clip, ci) => {
                  const c = resolveClip(clip)
                  const left = c.timelineStart * pxPerSec
                  const w = Math.max((c.timelineEnd - c.timelineStart) * pxPerSec, 6)
                  const selected = selection?.clipId === clip.id
                  const color = clip.color ?? clipColorByIndex(clip.segmentIndex ?? ci)
                  const isDragging = drag?.clipId === clip.id

                  return (
                    <div
                      key={clip.id}
                      data-clip-block
                      role="button"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation()
                        if (selection?.clipId !== clip.id) {
                          onSelectionChange({ clipId: clip.id, trackId: track.id })
                        }
                      }}
                      className={`absolute top-1 bottom-1 rounded-md border text-[10px] overflow-hidden cursor-pointer ${
                        clip.excluded
                          ? 'opacity-45 border-amber-700/50 bg-amber-950/40'
                          : color
                      } ${selected ? 'ring-2 ring-white/60 z-10' : 'z-[1]'} ${isDragging ? 'opacity-90 shadow-lg shadow-cyan-500/20' : ''}`}
                      style={{ left, width: w }}
                      title={`${clip.label} · ${fmtTime(c.timelineStart)}–${fmtTime(c.timelineEnd)}`}
                    >
                      {editable && !clip.excluded && (
                        <>
                          <div
                            className="absolute left-0 top-0 bottom-0 cursor-ew-resize z-20 group/handle"
                            style={{ width: HANDLE_W }}
                            onPointerDown={(e) => onPointerDownClip(e, clip, track.id, 'start')}
                          >
                            <span className="absolute inset-y-1 left-0.5 w-0.5 rounded-full bg-amber-300/80 opacity-60 group-hover/handle:opacity-100" />
                          </div>
                          <div
                            className="absolute right-0 top-0 bottom-0 cursor-ew-resize z-20 group/handle"
                            style={{ width: HANDLE_W }}
                            onPointerDown={(e) => onPointerDownClip(e, clip, track.id, 'end')}
                          >
                            <span className="absolute inset-y-1 right-0.5 w-0.5 rounded-full bg-cyan-300/80 opacity-60 group-hover/handle:opacity-100" />
                          </div>
                        </>
                      )}
                      <div className="px-1.5 py-0.5 truncate pointer-events-none">
                        <span className="font-medium text-white/95">{clip.label}</span>
                        {clip.subtitleText && track.kind === 'subtitle' && (
                          <span className="block truncate text-[9px] text-white/70">{clip.subtitleText}</span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
            )
          })}

          {/* 播放头竖线：贯穿所有轨道 */}
          <div
            className="absolute top-0 z-40 pointer-events-none"
            style={{ left: playheadLeft, height: TRACK_H * tracks.length + 28 }}
          >
            <button
              type="button"
              className="absolute -top-0 left-1/2 -translate-x-1/2 w-3 h-3 bg-red-500 border border-red-300 rounded-sm rotate-45 pointer-events-auto cursor-ew-resize shadow shadow-red-900/50"
              onPointerDown={onPointerDownPlayhead}
              title="拖动播放头"
            />
            <div className="absolute top-2 bottom-0 left-1/2 -translate-x-1/2 w-0.5 bg-red-500" />
          </div>
        </div>
      </div>

      {/* 底部 Scrubber */}
      <div
        className="h-7 border-t border-slate-800/80 bg-slate-950/90 relative cursor-pointer"
        onPointerDown={onPointerDownPlayhead}
      >
        <div
          className="absolute inset-y-1 rounded-full bg-slate-800/80"
          style={{ left: LABEL_W, right: 8 }}
        >
          <div
            className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full bg-red-500 border-2 border-red-300 shadow"
            style={{ left: `calc(${((playheadSec / duration) * 100).toFixed(3)}% - 5px)` }}
          />
        </div>
      </div>
    </div>
  )
}
