'use client'

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react'
import { EyeOff, Pause, Play, SkipBack, SkipForward } from 'lucide-react'
import type { AutoEditPlanApi } from '@/lib/api'
import {
  TimelineEditor,
  type TimelineSelection,
  type TimelineTrackState,
} from '@/components/timeline-editor'
import { clamp } from '@/components/timeline-editor'
import type { ClipMetaByClip, SelectedPreviewState } from './autoEditTypes'
import {
  applyPlanClipResize,
  applyPlanSegmentReorder,
  buildPlanSegmentLayouts,
  getNextActiveLayout,
  getSubtitleAtPlayhead,
  planLayoutsToTracks,
  playheadToSourceTime,
  sourceTimeToOutputTime,
  type PlanSegmentLayout,
} from './planTimelineAdapter'
import { clipStreamUrl, fmt, videoStreamUrl } from './types'
import {
  hasVisualEffectPreview,
  visualEffectToPreviewStyle,
} from './visualEffectPreview'
import type { SubtitleStyle } from '@/lib/subtitle-types'
import { DEFAULT_SUBTITLE_STYLE } from '@/lib/subtitle-types'
import { subtitleOverlayStyle } from '@/lib/subtitle-preview-style'

const SEG_END_EPS = 0.04

export type PlanEditWorkspaceProps = {
  plan: AutoEditPlanApi
  setPlan: Dispatch<SetStateAction<AutoEditPlanApi | null>>
  clipMetaByClip: ClipMetaByClip
  editable?: boolean
  planTitle?: string
  onExternalPreview?: (next: SelectedPreviewState) => void
  /** 工作台：字幕样式预览 */
  subtitleStyle?: SubtitleStyle
  subtitleEnabled?: boolean
  /** 工作台：BGM 时间轴块 */
  bgmTimeline?: { enabled: boolean; label: string }
  onBgmTrackFocus?: () => void
}

export function PlanEditWorkspace({
  plan,
  setPlan,
  clipMetaByClip,
  editable = false,
  planTitle = '方案',
  onExternalPreview,
  subtitleStyle,
  subtitleEnabled = true,
  bgmTimeline,
  onBgmTrackFocus,
}: PlanEditWorkspaceProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const layoutsRef = useRef<PlanSegmentLayout[]>([])
  const playheadRef = useRef(0)
  const rafRef = useRef<number | null>(null)
  const syncingFromVideoRef = useRef(false)
  const lockPlayheadRef = useRef(false)
  const currentLayoutIdRef = useRef<string | null>(null)

  const [playheadSec, setPlayheadSec] = useState(0)
  const [selection, setSelection] = useState<TimelineSelection>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playWholeTimeline, setPlayWholeTimeline] = useState(true)
  const [cssVisualPreview, setCssVisualPreview] = useState(true)
  const [previewSource, setPreviewSource] = useState<'video' | 'clip'>('video')
  const [trackStates, setTrackStates] = useState<Record<string, TimelineTrackState>>({
    video: { visible: true },
    audio: { muted: false },
    subtitle: { visible: true },
    bgm: { muted: false },
  })

  const segments = plan.segments ?? []
  const layouts = useMemo(
    () => buildPlanSegmentLayouts(segments, clipMetaByClip),
    [segments, clipMetaByClip],
  )
  layoutsRef.current = layouts
  playheadRef.current = playheadSec

  const { tracks, totalDuration } = useMemo(
    () =>
      planLayoutsToTracks(layouts, {
        allowSegmentReorder: editable,
        bgm: bgmTimeline?.enabled
          ? { enabled: true, label: bgmTimeline.label, totalDuration: 0 }
          : undefined,
      }),
    [layouts, editable, bgmTimeline?.enabled, bgmTimeline?.label],
  )

  const selectedLayout = useMemo(() => {
    if (!selection) return null
    return layouts.find((l) => l.segmentId === selection.clipId) ?? null
  }, [layouts, selection])

  const resolvedVideoId = useMemo(() => {
    const clipId = selectedLayout?.clipId
    if (!clipId) return null
    return clipMetaByClip[clipId]?.video_id ?? null
  }, [clipMetaByClip, selectedLayout?.clipId])

  const previewSrc = useMemo(() => {
    if (!selectedLayout?.clipId) return ''
    if (previewSource === 'video' && resolvedVideoId) return videoStreamUrl(resolvedVideoId)
    return clipStreamUrl(selectedLayout.clipId)
  }, [previewSource, resolvedVideoId, selectedLayout?.clipId])

  const setPlayhead = useCallback((sec: number, fromVideo = false) => {
    const v = clamp(sec, 0, totalDuration)
    playheadRef.current = v
    if (fromVideo) syncingFromVideoRef.current = true
    setPlayheadSec(v)
    if (fromVideo) {
      requestAnimationFrame(() => {
        syncingFromVideoRef.current = false
      })
    }
  }, [totalDuration])

  const seekVideoForLayout = useCallback(
    (layout: PlanSegmentLayout, sourceTime: number) => {
      const v = videoRef.current
      if (!v) return
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
    (layout: PlanSegmentLayout, sourceTime?: number) => {
      currentLayoutIdRef.current = layout.segmentId
      setSelection({ clipId: layout.segmentId, trackId: 'video' })
      const src = sourceTime ?? layout.sourceStart
      seekVideoForLayout(layout, src)
    },
    [seekVideoForLayout],
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

    const layoutId = currentLayoutIdRef.current
    const layout =
      layoutsRef.current.find((l) => l.segmentId === layoutId && !l.excluded) ??
      playheadToSourceTime(layoutsRef.current, playheadRef.current)?.layout

    if (!layout) return

    const sourceTime =
      previewSource === 'video' ? v.currentTime : layout.sourceStart + v.currentTime
    const outT = sourceTimeToOutputTime(layout, sourceTime)
    setPlayhead(outT, true)

    const reachedEnd =
      sourceTime >= layout.sourceEnd - SEG_END_EPS || outT >= layout.timelineEnd - SEG_END_EPS

    if (reachedEnd && playWholeTimeline && !v.paused) {
      const next = getNextActiveLayout(layoutsRef.current, layout)
      if (next) {
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
      const first = layouts.find((l) => !l.excluded)
      if (first) {
        currentLayoutIdRef.current = first.segmentId
        setSelection({ clipId: first.segmentId, trackId: 'video' })
      }
    }
  }, [plan.plan_id])

  useEffect(() => {
    if (syncingFromVideoRef.current || lockPlayheadRef.current) return
    const hit = playheadToSourceTime(layouts, playheadSec)
    if (!hit) return
    if (hit.layout.segmentId !== currentLayoutIdRef.current) {
      switchToLayout(hit.layout, hit.sourceTime)
    } else {
      seekVideoForLayout(hit.layout, hit.sourceTime)
    }
  }, [playheadSec, previewSrc, previewSource, layouts])

  const onPlayheadChange = (sec: number) => {
    setPlayhead(sec)
    const hit = playheadToSourceTime(layouts, sec)
    if (hit) switchToLayout(hit.layout, hit.sourceTime)
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
      const layout = layouts.find((l) => l.segmentId === args.clipId)
      if (!layout || layout.excluded) return
      const dur = args.timelineEnd - args.timelineStart
      const savedPlayhead = playheadRef.current
      lockPlayheadRef.current = true
      setPlan((prev) => {
        if (!prev) return prev
        return applyPlanClipResize(prev, layout.segIdx, args.edge, args.sourceStart, args.sourceEnd, dur)
      })
      requestAnimationFrame(() => {
        setPlayhead(savedPlayhead, true)
        const hit = playheadToSourceTime(layoutsRef.current, savedPlayhead)
        if (hit) seekVideoForLayout(hit.layout, hit.sourceTime)
        lockPlayheadRef.current = false
      })
    },
    [setPlan, layouts, seekVideoForLayout, setPlayhead],
  )

  const onClipMove = useCallback(
    (args: { clipId: string; timelineStart: number }) => {
      if (!editable) return
      setPlan((prev) => {
        if (!prev) return prev
        return applyPlanSegmentReorder(prev, args.clipId, args.timelineStart, clipMetaByClip)
      })
    },
    [clipMetaByClip, editable, setPlan],
  )

  const togglePlay = async () => {
    const v = videoRef.current
    if (!v) return
    if (!v.paused) {
      v.pause()
      return
    }
    let layout = layouts.find((l) => l.segmentId === currentLayoutIdRef.current && !l.excluded)
    if (!layout) {
      const hit = playheadToSourceTime(layouts, playheadSec)
      layout = hit?.layout ?? layouts.find((l) => !l.excluded)
    }
    if (!layout) return
    switchToLayout(layout, playheadToSourceTime(layouts, playheadSec)?.sourceTime ?? layout.sourceStart)
    try {
      await v.play()
    } catch {
      setIsPlaying(false)
    }
  }

  const jumpSegment = (dir: -1 | 1) => {
    const active = layouts.filter((l) => !l.excluded)
    const curIdx = active.findIndex((l) => l.segmentId === currentLayoutIdRef.current)
    const nextIdx = curIdx + dir
    if (nextIdx < 0 || nextIdx >= active.length) return
    const next = active[nextIdx]
    switchToLayout(next, next.sourceStart)
    setPlayhead(next.timelineStart)
  }

  const setInPointFromPlayhead = () => {
    if (!selectedLayout || !editable) return
    const hit = playheadToSourceTime(layouts, playheadSec)
    if (!hit || hit.layout.segmentId !== selectedLayout.segmentId) return
    onClipResize({
      clipId: selectedLayout.segmentId,
      edge: 'start',
      timelineStart: playheadSec,
      timelineEnd: selectedLayout.timelineEnd,
      sourceStart: hit.sourceTime,
      sourceEnd: selectedLayout.sourceEnd,
    })
    setPlayhead(playheadSec)
  }

  const setOutPointFromPlayhead = () => {
    if (!selectedLayout || !editable) return
    const hit = playheadToSourceTime(layouts, playheadSec)
    if (!hit || hit.layout.segmentId !== selectedLayout.segmentId) return
    onClipResize({
      clipId: selectedLayout.segmentId,
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

  const selectedSeg = selectedLayout ? segments[selectedLayout.segIdx] : null

  const videoTrackVisible = trackStates.video?.visible !== false
  const subtitlePreviewVisible =
    subtitleEnabled !== false && trackStates.subtitle?.visible !== false
  const audioMuted = trackStates.audio?.muted === true

  const previewSubtitleText = useMemo(() => {
    if (!subtitlePreviewVisible) return null
    return getSubtitleAtPlayhead(layouts, playheadSec)
  }, [subtitlePreviewVisible, layouts, playheadSec])

  const previewVisualStyle = useMemo(
    () => visualEffectToPreviewStyle(selectedLayout?.visualEffect),
    [selectedLayout?.visualEffect],
  )
  const previewVisualActive = hasVisualEffectPreview(selectedLayout?.visualEffect)
  const applyCssVisual = previewVisualActive && cssVisualPreview

  useEffect(() => {
    const v = videoRef.current
    if (v) v.muted = audioMuted
  }, [audioMuted, previewSrc])

  const handleTrackStateChange = useCallback((trackId: string, patch: Partial<TimelineTrackState>) => {
    setTrackStates((prev) => ({
      ...prev,
      [trackId]: { ...prev[trackId], ...patch },
    }))
  }, [])

  return (
    <div className="flex flex-col gap-3 min-h-0">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-3 min-h-[280px]">
        <div className="flex flex-col gap-2 min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] text-slate-500 truncate min-w-0">
              {selectedLayout
                ? `${planTitle} · ${selectedLayout.label} · ${fmt(selectedLayout.sourceStart)}–${fmt(selectedLayout.sourceEnd)}`
                : '点击时间轴选择片段'}
            </p>
            <div className="flex flex-wrap items-center gap-1.5 flex-shrink-0">
              <button
                type="button"
                onClick={() => jumpSegment(-1)}
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
                onClick={() => jumpSegment(1)}
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
              {previewVisualActive ? (
                <label className="inline-flex items-center gap-1 text-[10px] text-violet-300/90 cursor-pointer ml-1">
                  <input
                    type="checkbox"
                    checked={cssVisualPreview}
                    onChange={(e) => setCssVisualPreview(e.target.checked)}
                    className="rounded border-violet-600"
                  />
                  CSS 视觉预览
                </label>
              ) : null}
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
          </div>
          <div className="relative rounded-xl overflow-hidden border border-slate-800 bg-black flex-1 min-h-[200px] flex flex-col">
            {previewSrc ? (
              <>
              <div className="w-full flex-1 min-h-0 max-h-[38vh] flex items-center justify-center overflow-hidden">
              <div
                className="max-w-full max-h-full flex items-center justify-center origin-center"
                style={applyCssVisual ? previewVisualStyle : undefined}
              >
              <video
                ref={videoRef}
                key={previewSrc}
                src={previewSrc}
                className={`max-w-full max-h-[38vh] w-full h-full object-contain transition-opacity ${
                  videoTrackVisible ? 'opacity-100' : 'opacity-0'
                }`}
                controls={!applyCssVisual}
                playsInline
                onClick={() => {
                  if (applyCssVisual) void togglePlay()
                }}
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
                    (l) => l.segmentId === currentLayoutIdRef.current,
                  )
                  if (!layout) return
                  const next = getNextActiveLayout(layoutsRef.current, layout)
                  if (next) {
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
                  const hit = playheadToSourceTime(layoutsRef.current, playheadRef.current)
                  if (hit) seekVideoForLayout(hit.layout, hit.sourceTime)
                  if (videoRef.current) videoRef.current.muted = audioMuted
                }}
              />
              </div>
              </div>
              {applyCssVisual ? (
                <span className="absolute top-2 left-2 z-10 rounded-md border border-violet-500/40 bg-violet-950/80 px-1.5 py-0.5 text-[10px] text-violet-200 pointer-events-none">
                  视觉变换预览 · 请用上方播放/时间轴
                </span>
              ) : null}
              {!videoTrackVisible && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950 text-slate-500 pointer-events-none">
                  <EyeOff className="w-8 h-8 mb-2 opacity-40" />
                  <span className="text-xs">视频轨已隐藏</span>
                </div>
              )}
              {subtitlePreviewVisible && previewSubtitleText && (
                <div className="absolute inset-0 pointer-events-none z-10">
                  <p style={subtitleOverlayStyle(subtitleStyle ?? DEFAULT_SUBTITLE_STYLE)}>
                    {previewSubtitleText}
                  </p>
                </div>
              )}
              </>
            ) : (
              <div className="flex items-center justify-center h-[200px] text-sm text-slate-500">
                请选择片段预览
              </div>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 space-y-2 text-xs overflow-y-auto styled-scrollbar max-h-[42vh] lg:max-h-none">
          <p className="text-[11px] font-medium text-slate-400">片段属性</p>
          {!selectedSeg || !selectedLayout ? (
            <p className="text-slate-500 text-[11px]">点击时间轴片段查看与编辑</p>
          ) : (
            <>
              <p className="text-slate-200 font-semibold">
                {selectedLayout.label}
                {selectedSeg.exclude_from_output && (
                  <span className="ml-2 text-amber-400 text-[10px] font-normal">已弃用</span>
                )}
              </p>
              <label className="flex items-center gap-2 text-[11px] text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!selectedSeg.exclude_from_output}
                  disabled={!editable}
                  onChange={() => {
                    setPlan((prev) => {
                      if (!prev) return prev
                      const segs = [...(prev.segments ?? [])]
                      const i = selectedLayout.segIdx
                      segs[i] = { ...segs[i], exclude_from_output: !segs[i].exclude_from_output }
                      return { ...prev, segments: segs }
                    })
                  }}
                  className="rounded border-slate-600"
                />
                弃用本段
              </label>
              <label className="block text-[10px] text-slate-500">
                字幕
                <textarea
                  value={selectedSeg.subtitle?.text ?? ''}
                  readOnly={!editable}
                  rows={3}
                  onChange={(e) => {
                    if (!editable) return
                    setPlan((prev) => {
                      if (!prev) return prev
                      const segs = [...(prev.segments ?? [])]
                      const i = selectedLayout.segIdx
                      segs[i] = {
                        ...segs[i],
                        subtitle: {
                          strategy: segs[i].subtitle?.strategy ?? 'auto',
                          text: e.target.value,
                          source: 'user',
                        },
                      }
                      return { ...prev, segments: segs }
                    })
                  }}
                  className="mt-1 w-full rounded-md bg-slate-950/60 border border-slate-700 px-2 py-1 text-xs text-slate-200 outline-none focus:border-cyan-400 resize-y"
                />
              </label>
              <div className="grid grid-cols-2 gap-2 text-[10px] tabular-nums">
                <span className="text-slate-500">入点 {fmt(selectedLayout.sourceStart)}</span>
                <span className="text-slate-500">出点 {fmt(selectedLayout.sourceEnd)}</span>
                <span className="text-slate-500">成片 {fmt(selectedLayout.timelineStart)}</span>
                <span className="text-slate-500">时长 {selectedLayout.duration.toFixed(2)}s</span>
              </div>
              {previewVisualActive && selectedSeg.visual_effect ? (
                <p className="text-[10px] text-violet-300/90 leading-relaxed">
                  视觉变换：{cssVisualPreview ? 'CSS 近似预览已开' : '已关闭 CSS，原片预览'}
                  {selectedSeg.visual_effect.zoom != null && selectedSeg.visual_effect.zoom > 1
                    ? ` · 放大×${selectedSeg.visual_effect.zoom.toFixed(2)}`
                    : ''}
                  {selectedSeg.visual_effect.mirror ? ' · 镜像' : ''}
                  {selectedSeg.visual_effect.rotation_deg != null
                    ? ` · 旋转${selectedSeg.visual_effect.rotation_deg.toFixed(1)}°`
                    : ''}
                  {selectedSeg.visual_effect.color_intensity != null
                    ? ` · 调色${selectedSeg.visual_effect.color_intensity.toFixed(3)}`
                    : ''}
                </p>
              ) : null}
              {onExternalPreview && selectedLayout.clipId && (
                <button
                  type="button"
                  className="w-full text-[11px] rounded-lg border border-cyan-500/40 bg-cyan-500/10 py-1 text-cyan-200"
                  onClick={() =>
                    onExternalPreview({
                      planId: plan.plan_id,
                      planTitle,
                      segmentId: selectedLayout.segmentId,
                      order: selectedLayout.order,
                      clipId: selectedLayout.clipId,
                      videoId: clipMetaByClip[selectedLayout.clipId]?.video_id ?? null,
                      source: previewSource,
                      startSec: selectedLayout.sourceStart,
                      endSec: selectedLayout.sourceEnd,
                    })
                  }
                >
                  同步到上方预览条
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {editable && (
        <div className="flex flex-wrap items-center gap-2 px-1">
          <span className="text-[10px] text-slate-500">裁剪到竖线：</span>
          <button
            type="button"
            disabled={!selectedLayout}
            onClick={setInPointFromPlayhead}
            className="text-[11px] rounded-lg border border-amber-500/50 bg-amber-500/10 px-2.5 py-1 text-amber-200 hover:bg-amber-500/20 disabled:opacity-40"
            title="将当前片段入点裁到红色播放头（快捷键 I）"
          >
            裁剪入点 → 竖线
          </button>
          <button
            type="button"
            disabled={!selectedLayout}
            onClick={setOutPointFromPlayhead}
            className="text-[11px] rounded-lg border border-cyan-500/50 bg-cyan-500/10 px-2.5 py-1 text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-40"
            title="将当前片段出点裁到红色播放头（快捷键 O）"
          >
            裁剪出点 → 竖线
          </button>
          <span className="text-[10px] text-slate-600 tabular-nums">
            竖线 {fmt(playheadSec)}
          </span>
        </div>
      )}

      <TimelineEditor
        tracks={tracks}
        totalDuration={totalDuration}
        playheadSec={playheadSec}
        onPlayheadChange={onPlayheadChange}
        selection={selection}
        onSelectionChange={(sel) => {
          if (!sel) return
          if (sel.trackId === 'bgm') {
            setSelection(sel)
            onBgmTrackFocus?.()
            return
          }
          const isNewSegment = sel.clipId !== currentLayoutIdRef.current
          setSelection(sel)
          currentLayoutIdRef.current = sel.clipId
          if (isNewSegment) {
            const l = layouts.find((x) => x.segmentId === sel.clipId)
            if (l) {
              const hit = playheadToSourceTime(layouts, playheadRef.current)
              const srcTime =
                hit?.layout.segmentId === l.segmentId ? hit.sourceTime : l.sourceStart
              switchToLayout(l, srcTime)
            }
          }
        }}
        editable={editable}
        allowClipTrim={editable}
        allowClipReorder={editable}
        onClipResize={onClipResize}
        onClipMove={editable ? onClipMove : undefined}
        followPlayhead={isPlaying}
        onTrimDragChange={(active) => {
          lockPlayheadRef.current = active
        }}
        trackStates={trackStates}
        onTrackStateChange={handleTrackStateChange}
        className="flex-shrink-0"
      />

      <p className="text-[10px] text-slate-600 leading-relaxed">
        空格播放/暂停 · I/O 设入出点 · 方向键微调播放头 · 拖边缘裁剪（松手生效）
        {editable ? ' · 拖视频块中部可调整段落顺序' : ''}
        · 勾选「连续播放」可顺序预览全片。
      </p>
    </div>
  )
}
