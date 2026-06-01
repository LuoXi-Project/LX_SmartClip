'use client'

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { EyeOff, PanelBottom, PanelTop, Pause, Play, SkipBack, SkipForward } from 'lucide-react'
import {
  TimelineEditor,
  type TimelineSelection,
  type TimelineTrackState,
  clamp,
} from '@/components/timeline-editor'
import type { Segment } from './types'
import { clipStreamUrl, fmt, videoStreamUrl } from './types'
import {
  applySegmentClipResize,
  applySegmentReorder,
  buildSegmentClipLayouts,
  getNextSegmentLayout,
  getSubtitleAtPlayhead,
  parseBlockId,
  playheadToSegmentLayout,
  segmentLayoutsToTracks,
  type SegmentClipLayout,
} from './segmentTimelineAdapter'

const SEG_END_EPS = 0.04

export type SegmentTimelineWorkspaceProps = {
  segments: Segment[]
  onSegmentsChange: (next: Segment[]) => void
  focusedSegId?: string | null
  onFocusSegment?: (segId: string | null) => void
  workspaceTitle?: string
  editable?: boolean
  /** 是否允许在时间轴上拖块调整段落顺序（手动匹配开启；音频匹配与底音频对齐，关闭） */
  allowSegmentReorder?: boolean
  className?: string
}

export function SegmentTimelineWorkspace({
  segments,
  onSegmentsChange,
  focusedSegId,
  onFocusSegment,
  workspaceTitle = '成片时间轴',
  editable = true,
  allowSegmentReorder = false,
  className = '',
}: SegmentTimelineWorkspaceProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const layoutsRef = useRef<SegmentClipLayout[]>([])
  const playheadRef = useRef(0)
  const rafRef = useRef<number | null>(null)
  const syncingFromVideoRef = useRef(false)
  const lockPlayheadRef = useRef(false)
  const currentBlockIdRef = useRef<string | null>(null)

  const [playheadSec, setPlayheadSec] = useState(0)
  const [selection, setSelection] = useState<TimelineSelection>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playWholeTimeline, setPlayWholeTimeline] = useState(true)
  const [previewExpanded, setPreviewExpanded] = useState(true)
  const [pinTimelineBar, setPinTimelineBar] = useState(false)
  const [previewSource, setPreviewSource] = useState<'video' | 'clip'>('clip')
  const [trackStates, setTrackStates] = useState<Record<string, TimelineTrackState>>({
    video: { visible: true },
    audio: { muted: false },
    subtitle: { visible: true },
  })

  const layouts = useMemo(() => buildSegmentClipLayouts(segments), [segments])
  layoutsRef.current = layouts
  playheadRef.current = playheadSec

  const { tracks, totalDuration } = useMemo(
    () => segmentLayoutsToTracks(layouts, { allowSegmentReorder }),
    [layouts, allowSegmentReorder],
  )

  const selectedLayout = useMemo(() => {
    if (!selection) return null
    return layouts.find((l) => l.blockId === selection.clipId) ?? null
  }, [layouts, selection])

  const selectedSegment = useMemo(() => {
    const segId = selectedLayout?.segmentId ?? focusedSegId
    if (!segId) return null
    return segments.find((s) => s.id === segId) ?? null
  }, [focusedSegId, segments, selectedLayout?.segmentId])

  const resolvedVideoId = useMemo(() => {
    if (!selectedLayout?.clipId || !selectedSegment) return null
    const clip = selectedSegment.clips.find((c) => c.clip_id === selectedLayout.clipId)
    return clip?.video_id ?? null
  }, [selectedLayout?.clipId, selectedSegment])

  const previewSrc = useMemo(() => {
    if (!selectedLayout?.clipId || selectedLayout.placeholder) return ''
    if (previewSource === 'video' && resolvedVideoId) return videoStreamUrl(resolvedVideoId)
    return clipStreamUrl(selectedLayout.clipId)
  }, [previewSource, resolvedVideoId, selectedLayout?.clipId, selectedLayout?.placeholder])

  const readyCount = segments.filter((s) => getOrderedClipCount(s) > 0).length

  const setPlayhead = useCallback(
    (sec: number, fromVideo = false) => {
      const v = clamp(sec, 0, totalDuration)
      playheadRef.current = v
      if (fromVideo) syncingFromVideoRef.current = true
      setPlayheadSec(v)
      if (fromVideo) {
        requestAnimationFrame(() => {
          syncingFromVideoRef.current = false
        })
      }
    },
    [totalDuration],
  )

  const seekVideoForLayout = useCallback(
    (layout: SegmentClipLayout, sourceTime: number) => {
      const v = videoRef.current
      if (!v || layout.placeholder) return
      const t =
        previewSource === 'video'
          ? Math.max(0, sourceTime)
          : Math.max(0, sourceTime - layout.sourceStart)
      try {
        if (Number.isFinite(v.duration) && v.duration > 0) {
          v.currentTime = Math.min(t, Math.max(0, v.duration - 0.05))
        } else {
          v.currentTime = Math.max(0, t)
        }
      } catch {
        /* ignore */
      }
    },
    [previewSource],
  )

  const switchToLayout = useCallback(
    (layout: SegmentClipLayout, sourceTime?: number) => {
      currentBlockIdRef.current = layout.blockId
      setSelection({ clipId: layout.blockId, trackId: 'video' })
      onFocusSegment?.(layout.segmentId)
      if (!layout.placeholder) {
        seekVideoForLayout(layout, sourceTime ?? layout.sourceStart)
      }
    },
    [onFocusSegment, seekVideoForLayout],
  )

  const stopRaf = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }, [])

  const syncPlayheadFromVideo = useCallback(() => {
    const v = videoRef.current
    if (!v || syncingFromVideoRef.current) return

    const layoutId = currentBlockIdRef.current
    const layout =
      layoutsRef.current.find((l) => l.blockId === layoutId && !l.placeholder) ??
      playheadToSegmentLayout(layoutsRef.current, playheadRef.current)?.layout

    if (!layout || layout.placeholder) return

    const sourceTime =
      previewSource === 'video' ? v.currentTime : layout.sourceStart + v.currentTime
    const srcSpan = Math.max(SEG_END_EPS, layout.sourceEnd - layout.sourceStart)
    const rel = Math.min(1, Math.max(0, (sourceTime - layout.sourceStart) / srcSpan))
    const outT = layout.timelineStart + rel * layout.duration
    setPlayhead(outT, true)

    const reachedEnd =
      sourceTime >= layout.sourceEnd - SEG_END_EPS || outT >= layout.timelineEnd - SEG_END_EPS

    if (reachedEnd && playWholeTimeline && !v.paused) {
      const next = getNextSegmentLayout(layoutsRef.current, layout)
      if (next && !next.placeholder) {
        switchToLayout(next, next.sourceStart)
        setPlayhead(next.timelineStart, true)
        return
      }
      v.pause()
      setIsPlaying(false)
      setPlayhead(layout.timelineEnd, true)
      stopRaf()
    }
  }, [playWholeTimeline, previewSource, setPlayhead, stopRaf, switchToLayout])

  const startRaf = useCallback(() => {
    stopRaf()
    const loop = () => {
      syncPlayheadFromVideo()
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
  }, [stopRaf, syncPlayheadFromVideo])

  useEffect(() => () => stopRaf(), [stopRaf])

  useEffect(() => {
    if (!selection && layouts.length) {
      const first = layouts.find((l) => !l.placeholder) ?? layouts[0]
      if (first) {
        currentBlockIdRef.current = first.blockId
        setSelection({ clipId: first.blockId, trackId: 'video' })
      }
    }
  }, [segments.length])

  useEffect(() => {
    if (syncingFromVideoRef.current || lockPlayheadRef.current) return
    const hit = playheadToSegmentLayout(layouts, playheadSec)
    if (!hit || hit.layout.placeholder) return
    if (hit.layout.blockId !== currentBlockIdRef.current) {
      switchToLayout(hit.layout, hit.sourceTime)
    } else {
      seekVideoForLayout(hit.layout, hit.sourceTime)
    }
  }, [playheadSec, previewSrc, previewSource, layouts, seekVideoForLayout, switchToLayout])

  const onPlayheadChange = (sec: number) => {
    setPlayhead(sec)
    const hit = playheadToSegmentLayout(layouts, sec)
    if (hit && !hit.layout.placeholder) switchToLayout(hit.layout, hit.sourceTime)
  }

  const onClipResize = useCallback(
    (args: {
      clipId: string
      edge: 'start' | 'end'
      timelineStart: number
      timelineEnd: number
      sourceStart: number
      sourceEnd: number
    }) => {
      const layout = layouts.find((l) => l.blockId === args.clipId)
      if (!layout || layout.placeholder || !editable) return
      const savedPlayhead = playheadRef.current
      lockPlayheadRef.current = true
      onSegmentsChange(
        applySegmentClipResize(segments, args.clipId, args.sourceStart, args.sourceEnd),
      )
      requestAnimationFrame(() => {
        setPlayhead(savedPlayhead, true)
        const hit = playheadToSegmentLayout(layoutsRef.current, savedPlayhead)
        if (hit && !hit.layout.placeholder) seekVideoForLayout(hit.layout, hit.sourceTime)
        lockPlayheadRef.current = false
      })
    },
    [editable, layouts, onSegmentsChange, segments, seekVideoForLayout, setPlayhead],
  )

  const onClipMove = useCallback(
    (args: {
      clipId: string
      timelineStart: number
    }) => {
      if (!allowSegmentReorder || !editable) return
      const { segmentId, slotIndex } = parseBlockId(args.clipId)
      if (slotIndex > 0) return
      onSegmentsChange(applySegmentReorder(segments, segmentId, args.timelineStart))
    },
    [allowSegmentReorder, editable, onSegmentsChange, segments],
  )

  const togglePlay = async () => {
    const v = videoRef.current
    if (!v) return
    if (!v.paused) {
      v.pause()
      return
    }
    let layout =
      layouts.find((l) => l.blockId === currentBlockIdRef.current && !l.placeholder) ?? null
    if (!layout) {
      const hit = playheadToSegmentLayout(layouts, playheadSec)
      layout = hit?.layout.placeholder ? null : hit?.layout ?? null
    }
    if (!layout) {
      layout = layouts.find((l) => !l.placeholder) ?? null
    }
    if (!layout) return
    switchToLayout(
      layout,
      playheadToSegmentLayout(layouts, playheadSec)?.sourceTime ?? layout.sourceStart,
    )
    try {
      await v.play()
    } catch {
      setIsPlaying(false)
    }
  }

  const jumpBlock = (dir: -1 | 1) => {
    const playable = layouts.filter((l) => !l.placeholder)
    const curIdx = playable.findIndex((l) => l.blockId === currentBlockIdRef.current)
    const nextIdx = curIdx + dir
    if (nextIdx < 0 || nextIdx >= playable.length) return
    const next = playable[nextIdx]
    switchToLayout(next, next.sourceStart)
    setPlayhead(next.timelineStart)
  }

  const setInPointFromPlayhead = () => {
    if (!selectedLayout || !editable || selectedLayout.placeholder) return
    const hit = playheadToSegmentLayout(layouts, playheadSec)
    if (!hit || hit.layout.blockId !== selectedLayout.blockId) return
    onClipResize({
      clipId: selectedLayout.blockId,
      edge: 'start',
      timelineStart: playheadSec,
      timelineEnd: selectedLayout.timelineEnd,
      sourceStart: hit.sourceTime,
      sourceEnd: selectedLayout.sourceEnd,
    })
    setPlayhead(playheadSec)
  }

  const setOutPointFromPlayhead = () => {
    if (!selectedLayout || !editable || selectedLayout.placeholder) return
    const hit = playheadToSegmentLayout(layouts, playheadSec)
    if (!hit || hit.layout.blockId !== selectedLayout.blockId) return
    onClipResize({
      clipId: selectedLayout.blockId,
      edge: 'end',
      timelineStart: selectedLayout.timelineStart,
      timelineEnd: playheadSec,
      sourceStart: selectedLayout.sourceStart,
      sourceEnd: hit.sourceTime,
    })
    setPlayhead(playheadSec)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.code === 'Space') {
        e.preventDefault()
        void togglePlay()
      } else if (e.key === 'i' || e.key === 'I') {
        setInPointFromPlayhead()
      } else if (e.key === 'o' || e.key === 'O') {
        setOutPointFromPlayhead()
      } else if (e.key === 'ArrowLeft') {
        onPlayheadChange(Math.max(0, playheadRef.current - (e.shiftKey ? 1 : 0.1)))
      } else if (e.key === 'ArrowRight') {
        onPlayheadChange(Math.min(totalDuration, playheadRef.current + (e.shiftKey ? 1 : 0.1)))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  useEffect(() => {
    const v = videoRef.current
    if (v) v.muted = trackStates.audio?.muted === true
  }, [trackStates.audio?.muted, previewSrc])

  const handleTrackStateChange = useCallback((trackId: string, patch: Partial<TimelineTrackState>) => {
    setTrackStates((prev) => ({
      ...prev,
      [trackId]: { ...prev[trackId], ...patch },
    }))
  }, [])

  const handlePinTimelineBar = (next: boolean) => {
    setPinTimelineBar(next)
    if (next) setPreviewExpanded(false)
  }

  const transportControls = (
    <div className="flex flex-wrap items-center gap-1.5 flex-shrink-0">
      <button
        type="button"
        onClick={() => jumpBlock(-1)}
        className="p-1.5 rounded-lg border border-slate-700 text-slate-400 hover:bg-slate-800"
        title="上一段"
      >
        <SkipBack className="w-3.5 h-3.5" />
      </button>
      <button
        type="button"
        onClick={() => void togglePlay()}
        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-700 bg-slate-900 text-[11px] text-slate-200 hover:bg-slate-800"
      >
        {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
        {isPlaying ? '暂停' : '播放'}
      </button>
      <button
        type="button"
        onClick={() => jumpBlock(1)}
        className="p-1.5 rounded-lg border border-slate-700 text-slate-400 hover:bg-slate-800"
        title="下一段"
      >
        <SkipForward className="w-3.5 h-3.5" />
      </button>
      <label className="inline-flex items-center gap-1 text-[10px] text-slate-500 cursor-pointer ml-1">
        <input
          type="checkbox"
          checked={playWholeTimeline}
          onChange={(e) => setPlayWholeTimeline(e.target.checked)}
          className="rounded border-slate-600"
        />
        连续播放
      </label>
      <button
        type="button"
        disabled={!resolvedVideoId}
        onClick={() => setPreviewSource('video')}
        className={`text-[10px] rounded-md border px-1.5 py-0.5 ${
          previewSource === 'video'
            ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-200'
            : 'border-slate-700 text-slate-400'
        }`}
      >
        原视频
      </button>
      <button
        type="button"
        onClick={() => setPreviewSource('clip')}
        className={`text-[10px] rounded-md border px-1.5 py-0.5 ${
          previewSource === 'clip'
            ? 'border-cyan-500/50 bg-cyan-500/15 text-cyan-200'
            : 'border-slate-700 text-slate-400'
        }`}
      >
        片段
      </button>
    </div>
  )

  const videoTrackVisible = trackStates.video?.visible !== false
  const subtitlePreviewVisible = trackStates.subtitle?.visible !== false
  const previewSubtitleText = useMemo(() => {
    if (!subtitlePreviewVisible) return null
    return getSubtitleAtPlayhead(layouts, playheadSec)
  }, [subtitlePreviewVisible, layouts, playheadSec])

  const handleTimelineSelection = (sel: TimelineSelection) => {
    if (!sel) return
    let videoBlockId = sel.clipId
    if (sel.trackId === 'subtitle' && sel.clipId.endsWith('::sub')) {
      const segId = sel.clipId.replace('::sub', '')
      videoBlockId = layouts.find((l) => l.segmentId === segId)?.blockId ?? videoBlockId
    }
    const target = layouts.find((l) => l.blockId === videoBlockId)
    if (!target) return
    setSelection({ clipId: target.blockId, trackId: 'video' })
    currentBlockIdRef.current = target.blockId
    onFocusSegment?.(target.segmentId)
    if (!target.placeholder) {
      const hit = playheadToSegmentLayout(layouts, playheadRef.current)
      const srcTime =
        hit?.layout.blockId === target.blockId ? hit.sourceTime : target.sourceStart
      switchToLayout(target, srcTime)
    }
  }

  if (segments.length === 0) return null

  return (
    <section
      className={`rounded-2xl border border-indigo-500/25 bg-gradient-to-b from-indigo-950/20 to-slate-950/40 p-4 space-y-3 ${className}`}
      aria-label="剪辑时间轴工作区"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-indigo-200 uppercase tracking-widest">
            {workspaceTitle}
          </p>
          <p className="text-[11px] text-slate-500 mt-0.5">
            {readyCount}/{segments.length} 段已匹配 · 总长 {fmt(totalDuration)}
            {pinTimelineBar ? ' · 时间轴已固定底栏' : ''}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setPreviewExpanded((v) => !v)}
            className="inline-flex items-center gap-1 text-[10px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70"
          >
            {previewExpanded ? <PanelTop className="w-3 h-3" /> : <PanelBottom className="w-3 h-3" />}
            {previewExpanded ? '收起预览' : '展开预览'}
          </button>
          <label className="inline-flex items-center gap-1.5 text-[10px] text-slate-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={pinTimelineBar}
              onChange={(e) => handlePinTimelineBar(e.target.checked)}
              className="rounded border-slate-600"
            />
            底栏固定时间轴
          </label>
        </div>
      </div>

      <div className={`grid grid-cols-1 xl:grid-cols-[1fr_260px] gap-3 min-h-[200px] ${previewExpanded ? '' : 'hidden'}`}>
        <div className="flex flex-col gap-2 min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] text-slate-500 truncate min-w-0">
              {selectedLayout && !selectedLayout.placeholder
                ? `${selectedLayout.label} · ${fmt(selectedLayout.sourceStart)}–${fmt(selectedLayout.sourceEnd)}`
                : selectedLayout?.placeholder
                  ? `${selectedLayout.label} · 请先匹配素材`
                  : '点击时间轴选择片段'}
            </p>
            {transportControls}
          </div>

          <div className="relative rounded-xl overflow-hidden border border-slate-800 bg-black flex-1 min-h-[160px] flex flex-col">
            {previewSrc ? (
              <>
                <div className="w-full flex-1 min-h-0 max-h-[32vh] flex items-center justify-center overflow-hidden">
                  <video
                    ref={videoRef}
                    key={previewSrc}
                    src={previewSrc}
                    className={`max-w-full max-h-[32vh] w-full h-full object-contain transition-opacity ${
                      videoTrackVisible ? 'opacity-100' : 'opacity-0'
                    }`}
                    controls
                    playsInline
                    onPlay={() => {
                      setIsPlaying(true)
                      startRaf()
                    }}
                    onPause={() => {
                      setIsPlaying(false)
                      stopRaf()
                    }}
                    onEnded={() => {
                      if (!playWholeTimeline) return
                      const layout = layoutsRef.current.find(
                        (l) => l.blockId === currentBlockIdRef.current,
                      )
                      if (!layout) return
                      const next = getNextSegmentLayout(layoutsRef.current, layout)
                      if (next && !next.placeholder) {
                        switchToLayout(next, next.sourceStart)
                        setPlayhead(next.timelineStart)
                        void videoRef.current?.play()
                      } else {
                        setIsPlaying(false)
                        stopRaf()
                      }
                    }}
                    onSeeked={() => syncPlayheadFromVideo()}
                    onLoadedMetadata={() => {
                      const hit = playheadToSegmentLayout(layoutsRef.current, playheadRef.current)
                      if (hit && !hit.layout.placeholder) {
                        seekVideoForLayout(hit.layout, hit.sourceTime)
                      }
                      if (videoRef.current) {
                        videoRef.current.muted = trackStates.audio?.muted === true
                      }
                    }}
                  />
                </div>
                {!videoTrackVisible && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950 text-slate-500 pointer-events-none">
                    <EyeOff className="w-8 h-8 mb-2 opacity-40" />
                    <span className="text-xs">视频轨已隐藏</span>
                  </div>
                )}
                {subtitlePreviewVisible && previewSubtitleText && (
                  <div className="absolute inset-x-0 bottom-6 px-6 flex justify-center pointer-events-none z-10">
                    <p
                      className="max-w-[92%] text-center text-lg sm:text-xl font-bold leading-snug text-white px-3 py-1.5 rounded"
                      style={{
                        textShadow:
                          '0 0 4px rgba(0,0,0,1), 0 1px 2px rgba(0,0,0,0.95), 1px 1px 0 #000, -1px -1px 0 #000',
                      }}
                    >
                      {previewSubtitleText}
                    </p>
                  </div>
                )}
              </>
            ) : (
              <div className="flex flex-col items-center justify-center h-[160px] text-sm text-slate-500 gap-2 px-6 text-center">
                <p>时间轴即作品本体</p>
                <p className="text-[11px] text-slate-600">
                  在下方段落中匹配素材后，可在此预览、裁剪出入点并顺序浏览全片
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 space-y-2 text-xs overflow-y-auto max-h-[48vh] xl:max-h-none">
          <p className="text-[11px] font-medium text-slate-400">当前段落</p>
          {!selectedSegment ? (
            <p className="text-slate-500 text-[11px]">点击时间轴片段查看属性</p>
          ) : (
            <>
              <p className="text-slate-200 font-semibold">
                段落 {selectedSegment.text.slice(0, 24) || '（无文案）'}
                {selectedSegment.text.length > 24 ? '…' : ''}
              </p>
              <p className="text-[11px] text-slate-500 leading-relaxed line-clamp-4">
                {selectedSegment.text || '暂无文案'}
              </p>
              {selectedLayout && !selectedLayout.placeholder && (
                <p className="text-[10px] text-slate-600 pt-1">
                  素材 {selectedLayout.clipId.slice(0, 8)}… · 成片{' '}
                  {fmt(selectedLayout.timelineStart)}–{fmt(selectedLayout.timelineEnd)}
                </p>
              )}
            </>
          )}
        </div>
      </div>

      <div
        className={
          pinTimelineBar
            ? 'sticky bottom-0 z-20 -mx-4 px-4 pt-2 pb-3 border-t border-indigo-500/20 bg-[#0d0f14]/95 backdrop-blur-md shadow-[0_-10px_28px_rgba(0,0,0,0.45)] space-y-2'
            : 'space-y-2'
        }
      >
        {!previewExpanded && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] text-slate-500 truncate min-w-0">
              {selectedLayout && !selectedLayout.placeholder
                ? `${selectedLayout.label} · ${fmt(playheadSec)} / ${fmt(totalDuration)}`
                : '时间轴'}
            </p>
            {transportControls}
          </div>
        )}

      <TimelineEditor
        tracks={tracks}
        totalDuration={totalDuration}
        playheadSec={playheadSec}
        onPlayheadChange={onPlayheadChange}
        selection={selection}
        onSelectionChange={handleTimelineSelection}
        editable={editable}
        allowClipTrim={editable}
        allowClipReorder={editable && allowSegmentReorder}
        onClipResize={onClipResize}
        onClipMove={allowSegmentReorder ? onClipMove : undefined}
        followPlayhead={isPlaying}
        onTrimDragChange={(active) => {
          lockPlayheadRef.current = active
        }}
        trackStates={trackStates}
        onTrackStateChange={handleTrackStateChange}
        className="flex-shrink-0"
      />

      {!pinTimelineBar && (
      <p className="text-[10px] text-slate-600 leading-relaxed">
        空格播放/暂停 · I/O 设入出点 · 方向键微调播放头 · 拖边缘裁剪（松手生效）
        {allowSegmentReorder ? ' · 拖视频块中部可调整段落顺序' : ''}
        · 勾选「连续播放」可顺序预览全片。
      </p>
      )}
      </div>
    </section>
  )
}

function getOrderedClipCount(seg: Segment): number {
  const ids = seg.selectedClipIds ?? []
  if (ids.length) return ids.length
  return seg.clips[seg.chosenIdx]?.clip_id ? 1 : 0
}
