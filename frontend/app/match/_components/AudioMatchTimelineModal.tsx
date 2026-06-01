'use client'

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Pause, Play, SkipBack, SkipForward } from 'lucide-react'
import { audioMatchApi } from '@/lib/api'
import {
  TimelineEditor,
  clamp,
  type TimelineSelection,
  type TimelineTrackState,
} from '@/components/timeline-editor'
import type { Segment } from './types'
import { fmt } from './types'
import {
  applyAudioMatchTimelineEdit,
  getSegmentAtSourceTime,
  segmentsToSourceTimelineTracks,
} from './audioMatchTimelineAdapter'

export type AudioMatchTimelineModalProps = {
  open: boolean
  onClose: () => void
  segments: Segment[]
  sourceFilename: string
  sourceDurationSec: number
  /** 从某段「微调时间」进入时聚焦该段 */
  initialSegId?: string | null
  onSave: (next: Segment[]) => void
  saving?: boolean
}

export function AudioMatchTimelineModal({
  open,
  onClose,
  segments,
  sourceFilename,
  sourceDurationSec,
  initialSegId,
  onSave,
  saving = false,
}: AudioMatchTimelineModalProps) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const playheadRef = useRef(0)
  const lockPlayheadRef = useRef(false)

  const [draft, setDraft] = useState<Segment[]>(segments)
  const [playheadSec, setPlayheadSec] = useState(0)
  const [selection, setSelection] = useState<TimelineSelection>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playContinuous, setPlayContinuous] = useState(true)
  const [trackStates, setTrackStates] = useState<Record<string, TimelineTrackState>>({
    segment: { visible: true },
    audio: { muted: false },
    subtitle: { visible: true },
  })

  const sourceUrl = useMemo(
    () => (sourceFilename ? audioMatchApi.sourceUrl(sourceFilename) : ''),
    [sourceFilename],
  )

  const { tracks, totalDuration } = useMemo(
    () => segmentsToSourceTimelineTracks(draft, sourceDurationSec),
    [draft, sourceDurationSec],
  )

  const selectedSeg = useMemo(() => {
    if (!selection) return null
    return draft.find((s) => s.id === selection.clipId) ?? null
  }, [draft, selection])

  const selectedIndex = selectedSeg ? draft.findIndex((s) => s.id === selectedSeg.id) : -1

  const previewText = useMemo(() => {
    const hit = getSegmentAtSourceTime(draft, playheadSec)
    return hit?.text.trim() || null
  }, [draft, playheadSec])

  playheadRef.current = playheadSec

  useEffect(() => {
    if (!open) return
    setDraft(segments)
    const focus = initialSegId
      ? segments.find((s) => s.id === initialSegId)
      : segments[0]
    const t = focus?.audioStartSec ?? 0
    setPlayheadSec(t)
    if (focus) setSelection({ clipId: focus.id, trackId: 'audio' })
    else setSelection(null)
    setIsPlaying(false)
  }, [open, segments, initialSegId])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    const a = audioRef.current
    if (!a || lockPlayheadRef.current) return
    if (Math.abs(a.currentTime - playheadSec) > 0.12) {
      try {
        a.currentTime = clamp(playheadSec, 0, totalDuration)
      } catch {
        /* ignore */
      }
    }
  }, [playheadSec, totalDuration])

  const setPlayhead = useCallback((sec: number) => {
    const v = clamp(sec, 0, totalDuration)
    playheadRef.current = v
    setPlayheadSec(v)
  }, [totalDuration])

  const seekAudio = useCallback((sec: number) => {
    const a = audioRef.current
    if (!a) return
    const v = clamp(sec, 0, totalDuration)
    try {
      a.currentTime = v
    } catch {
      /* ignore */
    }
    setPlayhead(v)
  }, [setPlayhead, totalDuration])

  const togglePlay = async () => {
    const a = audioRef.current
    if (!a) return
    if (!a.paused) {
      a.pause()
      return
    }
    try {
      await a.play()
    } catch {
      setIsPlaying(false)
    }
  }

  const jumpSegment = (dir: -1 | 1) => {
    const list = draft.filter(
      (s) => s.audioStartSec != null && s.audioEndSec != null && s.audioEndSec > s.audioStartSec,
    )
    const curIdx = selectedSeg ? list.findIndex((s) => s.id === selectedSeg.id) : -1
    const nextIdx = curIdx < 0 ? (dir > 0 ? 0 : list.length - 1) : curIdx + dir
    if (nextIdx < 0 || nextIdx >= list.length) return
    const next = list[nextIdx]
    setSelection({ clipId: next.id, trackId: 'audio' })
    seekAudio(next.audioStartSec ?? 0)
  }

  const onClipResize = useCallback(
    (args: {
      clipId: string
      sourceStart: number
      sourceEnd: number
    }) => {
      setDraft((prev) =>
        applyAudioMatchTimelineEdit(
          prev,
          args.clipId,
          args.sourceStart,
          args.sourceEnd,
          totalDuration,
        ),
      )
    },
    [totalDuration],
  )

  const setInFromPlayhead = () => {
    if (!selectedSeg || selectedIndex < 0) return
    const end = selectedSeg.audioEndSec ?? playheadSec + 0.08
    onClipResize({
      clipId: selectedSeg.id,
      sourceStart: playheadSec,
      sourceEnd: end,
    })
  }

  const setOutFromPlayhead = () => {
    if (!selectedSeg || selectedIndex < 0) return
    const start = selectedSeg.audioStartSec ?? 0
    onClipResize({
      clipId: selectedSeg.id,
      sourceStart: start,
      sourceEnd: playheadSec,
    })
  }

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.code === 'Space') {
        e.preventDefault()
        void togglePlay()
      } else if (e.key === 'i' || e.key === 'I') {
        setInFromPlayhead()
      } else if (e.key === 'o' || e.key === 'O') {
        setOutFromPlayhead()
      } else if (e.key === 'ArrowLeft') {
        seekAudio(playheadRef.current - (e.shiftKey ? 1 : 0.1))
      } else if (e.key === 'ArrowRight') {
        seekAudio(playheadRef.current + (e.shiftKey ? 1 : 0.1))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const handleTimeUpdate = () => {
    const a = audioRef.current
    if (!a || lockPlayheadRef.current) return
    setPlayheadSec(a.currentTime)

    if (!playContinuous || a.paused) return
    const hit = getSegmentAtSourceTime(draft, a.currentTime)
    if (!hit) return
    const end = hit.audioEndSec ?? 0
    if (a.currentTime >= end - 0.04) {
      const list = draft.filter(
        (s) => s.audioStartSec != null && s.audioEndSec != null,
      )
      const idx = list.findIndex((s) => s.id === hit.id)
      const next = idx >= 0 && idx < list.length - 1 ? list[idx + 1] : null
      if (next) {
        setSelection({ clipId: next.id, trackId: 'audio' })
        try {
          a.currentTime = next.audioStartSec ?? 0
        } catch {
          /* ignore */
        }
      } else {
        a.pause()
      }
    }
  }

  if (!open) return null

  const hasChanges =
    JSON.stringify(draft.map((s) => [s.id, s.audioStartSec, s.audioEndSec, s.text])) !==
    JSON.stringify(segments.map((s) => [s.id, s.audioStartSec, s.audioEndSec, s.text]))

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label="底音频时间轴剪辑"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
        aria-label="关闭"
      />
      <div className="relative flex flex-col w-full max-w-[min(96vw,1280px)] max-h-[min(92vh,900px)] rounded-2xl border border-slate-800 bg-[#0d0f14] shadow-2xl overflow-hidden">
        <div className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-3 flex-shrink-0">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-100 truncate">底音频 · 时间轴剪辑</p>
            <p className="text-[11px] text-slate-500 mt-0.5">
              {draft.length} 段 · 总长 {fmt(totalDuration)} · 拖动边缘微调各段在配音中的起止
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70 flex-shrink-0"
          >
            关闭 Esc
          </button>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 px-4 py-2 border-b border-slate-800/80 bg-slate-950/40 flex-shrink-0">
          <button
            type="button"
            disabled={!hasChanges || saving}
            onClick={() => onSave(draft)}
            className="text-[11px] rounded-lg border border-emerald-500/60 bg-emerald-500/15 px-2.5 py-1 text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
          >
            {saving ? '保存并切片中…' : '保存并刷新切片'}
          </button>
          <button
            type="button"
            onClick={() => {
              setDraft(segments)
              onClose()
            }}
            className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70"
          >
            取消
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 min-h-0">
          <div className="flex flex-col gap-3 min-h-0">
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-3 min-h-[200px]">
              <div className="flex flex-col gap-2 min-w-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[11px] text-slate-500 truncate min-w-0 tabular-nums">
                    {selectedSeg && selectedIndex >= 0
                      ? `段落 ${selectedIndex + 1} · ${fmt(selectedSeg.audioStartSec ?? 0)}–${fmt(selectedSeg.audioEndSec ?? 0)}`
                      : '点击时间轴选择段落'}
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
                        checked={playContinuous}
                        onChange={(e) => setPlayContinuous(e.target.checked)}
                        className="rounded border-slate-600"
                      />
                      连续播放
                    </label>
                  </div>
                </div>

                <div className="relative rounded-xl overflow-hidden border border-slate-800 bg-slate-950 flex flex-col min-h-[140px]">
                  <audio
                    ref={audioRef}
                    key={sourceUrl}
                    src={sourceUrl}
                    className="w-full"
                    controls
                    onPlay={() => setIsPlaying(true)}
                    onPause={() => setIsPlaying(false)}
                    onTimeUpdate={handleTimeUpdate}
                    onLoadedMetadata={() => seekAudio(playheadRef.current)}
                  />
                  {trackStates.subtitle?.visible !== false && previewText && (
                    <div className="px-4 pb-3 pt-1 border-t border-slate-800/80">
                      <p className="text-sm text-slate-200 leading-relaxed">{previewText}</p>
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 space-y-2 text-xs overflow-y-auto max-h-[42vh] lg:max-h-none">
                <p className="text-[11px] font-medium text-slate-400">段落属性</p>
                {!selectedSeg || selectedIndex < 0 ? (
                  <p className="text-slate-500 text-[11px]">点击时间轴片段查看与编辑</p>
                ) : (
                  <>
                    <p className="text-slate-200 font-semibold">段落 {selectedIndex + 1}</p>
                    <label className="block text-[10px] text-slate-500">
                      文案
                      <textarea
                        value={selectedSeg.text}
                        rows={4}
                        onChange={(e) => {
                          const text = e.target.value
                          setDraft((prev) =>
                            prev.map((s) => (s.id === selectedSeg.id ? { ...s, text } : s)),
                          )
                        }}
                        className="mt-1 w-full rounded-md bg-slate-950/60 border border-slate-700 px-2 py-1 text-xs text-slate-200 outline-none focus:border-rose-400 resize-y"
                      />
                    </label>
                    <div className="grid grid-cols-2 gap-2 text-[10px] tabular-nums">
                      <span className="text-slate-500">入点 {fmt(selectedSeg.audioStartSec ?? 0)}</span>
                      <span className="text-slate-500">出点 {fmt(selectedSeg.audioEndSec ?? 0)}</span>
                      <span className="text-slate-500 col-span-2">
                        时长 {((selectedSeg.audioEndSec ?? 0) - (selectedSeg.audioStartSec ?? 0)).toFixed(2)}s
                      </span>
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 px-1">
              <span className="text-[10px] text-slate-500">裁剪到竖线：</span>
              <button
                type="button"
                disabled={!selectedSeg}
                onClick={setInFromPlayhead}
                className="text-[11px] rounded-lg border border-amber-500/50 bg-amber-500/10 px-2.5 py-1 text-amber-200 hover:bg-amber-500/20 disabled:opacity-40"
              >
                裁剪入点 → 竖线
              </button>
              <button
                type="button"
                disabled={!selectedSeg}
                onClick={setOutFromPlayhead}
                className="text-[11px] rounded-lg border border-cyan-500/50 bg-cyan-500/10 px-2.5 py-1 text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-40"
              >
                裁剪出点 → 竖线
              </button>
              <span className="text-[10px] text-slate-600 tabular-nums">竖线 {fmt(playheadSec)}</span>
            </div>

            <TimelineEditor
              tracks={tracks}
              totalDuration={totalDuration}
              playheadSec={playheadSec}
              onPlayheadChange={seekAudio}
              selection={selection}
              onSelectionChange={(sel) => {
                if (!sel) return
                setSelection(sel)
                const seg = draft.find((s) => s.id === sel.clipId)
                if (seg?.audioStartSec != null) seekAudio(seg.audioStartSec)
              }}
              editable
              allowClipTrim
              allowClipReorder={false}
              onClipResize={(args) => {
                onClipResize({
                  clipId: args.clipId,
                  sourceStart: args.sourceStart,
                  sourceEnd: args.sourceEnd,
                })
              }}
              followPlayhead={isPlaying}
              onTrimDragChange={(active) => {
                lockPlayheadRef.current = active
              }}
              trackStates={trackStates}
              onTrackStateChange={(trackId, patch) => {
                setTrackStates((prev) => ({
                  ...prev,
                  [trackId]: { ...prev[trackId], ...patch },
                }))
              }}
              className="flex-shrink-0"
            />

            <p className="text-[10px] text-slate-600 leading-relaxed">
              空格播放/暂停 · I/O 设入出点 · 方向键微调播放头 · 拖边缘调整段落时间 · 保存后将按新时间重新切片原声。
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
