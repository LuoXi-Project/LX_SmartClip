'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, Pause, Play, Plus, Search, SplitSquareHorizontal } from 'lucide-react'
import { type BgmTrack, type MatchClip } from '@/lib/api'
import { type Segment } from './types'
import { CopyGeneratorPanel } from './CopyGeneratorPanel'
import { SegmentRow } from './SegmentRow'

function formatAudioTime(sec: number) {
  if (!Number.isFinite(sec) || sec < 0) return '00:00'
  const total = Math.floor(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export type ManualMatchPanelProps = {
  topK: number
  topN: number
  onTopKChange: (value: number) => void
  onTopNChange: (value: number) => void
  selectedVideoIds: string[]
  onAiApply: (parts: string[]) => void
  globalQuery: string
  onGlobalQueryChange: (value: string) => void
  onSplit: () => void
  onMatchAll: () => void
  globalMatching: boolean
  onAddSegment: () => void
  /** 拖动段落调整顺序：将 fromId 移到 toId 所在位置 */
  onMoveSegment: (fromId: string, toId: string) => void
  /** 按钮调整顺序 */
  onSegmentReorder: (segId: string, action: 'up' | 'down' | 'top' | 'bottom') => void
  segments: Segment[]
  onClearAll: () => void
  onSegmentTextChange: (segId: string, text: string) => void
  onRemoveSegment: (segId: string) => void
  onMatchSegment: (segId: string) => void
  onToggleClipSelected: (segId: string, clipId: string) => void
  onSynthesiseTts: (segId: string) => void
  onPlayAudio: (segId: string) => void
  onStopAudio: () => void
  onSeekAudio?: (segId: string, timeSeconds: number) => void
  playingSegId: string | null
  audioCurrentTime?: number
  audioDuration?: number
  onPreview: (clip: MatchClip) => void
  onToggleExpand: (segId: string) => void
  /** 打开段落主选素材的出入点预览 */
  onOpenClipInOut?: (segId: string) => void
  /** 复刻模板向导：用于自动注入到文案生成提示词前缀 */
  replicaTemplateGuide?: string
  manualBgmEnabled: boolean
  onManualBgmEnabledChange: (value: boolean) => void
  bgmTracks: BgmTrack[]
  selectedManualBgmTrackIds: string[]
  onToggleManualBgmTrack: (trackId: string) => void
  manualBgmVolumeByTrackId: Record<string, number>
  onManualBgmTrackVolumeChange: (trackId: string, volumeDb: number) => void
  manualBgmTimelineSegments: Array<{ id: string; startSec: number; endSec: number; trackId?: string; volumeDb?: number }>
  onAddManualBgmTimelineSegment: () => void
  onRemoveManualBgmTimelineSegment: (id: string) => void
  onUpdateManualBgmTimelineSegment: (
    id: string,
    patch: Partial<{ startSec: number; endSec: number; trackId?: string; volumeDb?: number }>
  ) => void
  bgmListError?: string
}

export function ManualMatchPanel({
  topK,
  topN,
  onTopKChange,
  onTopNChange,
  selectedVideoIds,
  onAiApply,
  globalQuery,
  onGlobalQueryChange,
  onSplit,
  onMatchAll,
  globalMatching,
  onAddSegment,
  onMoveSegment,
  onSegmentReorder,
  segments,
  onClearAll,
  onSegmentTextChange,
  onRemoveSegment,
  onMatchSegment,
  onToggleClipSelected,
  onSynthesiseTts,
  onPlayAudio,
  onStopAudio,
  onSeekAudio,
  playingSegId,
  audioCurrentTime = 0,
  audioDuration = 0,
  onPreview,
  onToggleExpand,
  onOpenClipInOut,
  replicaTemplateGuide,
  manualBgmEnabled,
  onManualBgmEnabledChange,
  bgmTracks,
  selectedManualBgmTrackIds,
  onToggleManualBgmTrack,
  manualBgmVolumeByTrackId,
  onManualBgmTrackVolumeChange,
  manualBgmTimelineSegments,
  onAddManualBgmTimelineSegment,
  onRemoveManualBgmTimelineSegment,
  onUpdateManualBgmTimelineSegment,
  bgmListError,
}: ManualMatchPanelProps) {
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dropTargetId, setDropTargetId] = useState<string | null>(null)
  const [flashId, setFlashId] = useState<string | null>(null)
  const [bgmKeyword, setBgmKeyword] = useState('')
  const [previewTrackId, setPreviewTrackId] = useState<string | null>(null)
  const [previewCurrentTime, setPreviewCurrentTime] = useState(0)
  const [previewDuration, setPreviewDuration] = useState(0)
  const flashClearRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const previewAudioRefs = useRef<Record<string, HTMLAudioElement | null>>({})
  const dragMime = 'application/x-smartclip-seg-id'
  const normalizedBgmKeyword = bgmKeyword.trim().toLowerCase()
  const filteredBgmTracks = useMemo(() => {
    if (!normalizedBgmKeyword) return bgmTracks
    return bgmTracks.filter((track) => {
      const searchable = [
        track.title,
        track.filename,
        track.mood ?? '',
        String(track.bpm ?? ''),
        ...(track.tags ?? []),
      ]
        .join(' ')
        .toLowerCase()
      return searchable.includes(normalizedBgmKeyword)
    })
  }, [bgmTracks, normalizedBgmKeyword])

  const flashRow = (id: string) => {
    if (flashClearRef.current) clearTimeout(flashClearRef.current)
    setFlashId(id)
    flashClearRef.current = setTimeout(() => {
      setFlashId(null)
      flashClearRef.current = null
    }, 1100)
  }

  useEffect(() => () => {
    if (flashClearRef.current) clearTimeout(flashClearRef.current)
  }, [])
  useEffect(() => () => {
    Object.values(previewAudioRefs.current).forEach((audio) => audio?.pause())
  }, [])

  /** 拖动靠近视口上下边缘时自动滚动，便于长列表排序 */
  useEffect(() => {
    if (!draggingId) return
    const margin = 88
    const maxStep = 22
    const onDragOver = (e: DragEvent) => {
      const y = e.clientY
      if (y < margin) {
        const k = 1 - y / margin
        window.scrollBy(0, -Math.ceil(maxStep * k))
      } else if (y > window.innerHeight - margin) {
        const k = 1 - (window.innerHeight - y) / margin
        window.scrollBy(0, Math.ceil(maxStep * k))
      }
    }
    document.addEventListener('dragover', onDragOver)
    return () => document.removeEventListener('dragover', onDragOver)
  }, [draggingId])

  return (
    <>
      <div className="flex flex-wrap items-center gap-4">
        <label className="text-xs text-slate-500 flex items-center gap-2">
          初筛
          <input
            type="number"
            min={1}
            max={50}
            value={topK}
            onChange={(e) => onTopKChange(Number(e.target.value))}
            className="w-14 rounded-lg bg-slate-800 border border-slate-700 px-2 py-1 text-center text-slate-200"
          />
        </label>
        <label className="text-xs text-slate-500 flex items-center gap-2">
          推荐
          <input
            type="number"
            min={1}
            max={20}
            value={topN}
            onChange={(e) => onTopNChange(Number(e.target.value))}
            className="w-14 rounded-lg bg-slate-800 border border-slate-700 px-2 py-1 text-center text-slate-200"
          />
        </label>
      </div>
      <CopyGeneratorPanel
        selectedVideoIds={selectedVideoIds}
        onApply={onAiApply}
        replicaTemplateGuide={replicaTemplateGuide}
      />
      <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">手动 BGM</p>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={manualBgmEnabled}
            onChange={(e) => onManualBgmEnabledChange(e.target.checked)}
            className="rounded border-slate-600 bg-slate-900 text-emerald-500 focus:ring-emerald-500/40"
          />
          <span className="text-sm text-slate-200">导出时混入 BGM（支持多选循环、分段配置）</span>
        </label>
        {manualBgmEnabled && (
          <div className="space-y-3">
            <div className="rounded-xl border border-slate-700/70 bg-slate-950/50 p-3 space-y-2">
              <p className="text-xs text-slate-400">可用 BGM（勾选后按列表顺序循环）</p>
              {bgmTracks.length === 0 ? (
                <p className="text-xs text-slate-500">{bgmListError || '暂无 BGM，请先到 BGM 页面上传。'}</p>
              ) : (
                <div className="space-y-2">
                  <input
                    type="text"
                    value={bgmKeyword}
                    onChange={(e) => setBgmKeyword(e.target.value)}
                    placeholder="搜索 BGM：名称 / 文件名 / 标签 / 心情 / BPM"
                    className="w-full rounded-lg bg-slate-900 border border-slate-700 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                  <div className="space-y-1.5 max-h-72 overflow-auto pr-1">
                    {filteredBgmTracks.map((t) => {
                    const picked = selectedManualBgmTrackIds.includes(t.filename)
                    const isPreviewing = previewTrackId === t.id
                    return (
                      <div key={t.id} className="rounded-lg border border-slate-800 px-2 py-1.5">
                        <div className="flex items-center gap-2 rounded-md bg-slate-900/70">
                          <input
                            type="checkbox"
                            checked={picked}
                            onChange={() => onToggleManualBgmTrack(t.filename)}
                            className="rounded border-slate-600 bg-slate-900 text-emerald-500 focus:ring-emerald-500/40"
                          />
                          <span className="text-xs text-slate-200 w-40 shrink-0 truncate">
                            {t.title || t.filename}
                            {picked ? (
                              <span className="ml-1 text-[10px] text-emerald-400/90">
                                #{selectedManualBgmTrackIds.indexOf(t.filename) + 1}
                              </span>
                            ) : null}
                          </span>
                          <label className="text-[10px] text-slate-500 flex items-center gap-1 shrink-0">
                            dB
                            <input
                              type="number"
                              step={0.5}
                              min={-40}
                              max={12}
                              value={manualBgmVolumeByTrackId[t.filename] ?? -14}
                              onChange={(e) => onManualBgmTrackVolumeChange(t.filename, Number(e.target.value))}
                              className="w-16 rounded bg-slate-900 border border-slate-700 px-1.5 py-0.5 text-[11px] text-slate-200"
                            />
                          </label>
                          <button
                            type="button"
                            onClick={() => {
                              const current = previewAudioRefs.current[t.id]
                              if (!current) return
                              if (isPreviewing) {
                                current.pause()
                                setPreviewTrackId(null)
                                return
                              }
                              if (previewTrackId && previewTrackId !== t.id) {
                                previewAudioRefs.current[previewTrackId]?.pause()
                              }
                              void current.play()
                              setPreviewTrackId(t.id)
                            }}
                            className="h-7 w-7 shrink-0 rounded-full border border-slate-700 bg-slate-800 text-slate-200 hover:border-indigo-500 hover:text-indigo-300 flex items-center justify-center"
                            aria-label={isPreviewing ? '暂停试听' : '播放试听'}
                          >
                            {isPreviewing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5 ml-0.5" />}
                          </button>
                          <input
                            type="range"
                            min={0}
                            max={isPreviewing && previewDuration > 0 ? previewDuration : 0}
                            step={0.01}
                            value={isPreviewing ? Math.min(previewCurrentTime, previewDuration || 0) : 0}
                            onChange={(e) => {
                              const next = Number(e.target.value)
                              const audio = previewAudioRefs.current[t.id]
                              if (!audio) return
                              audio.currentTime = next
                              if (isPreviewing) setPreviewCurrentTime(next)
                            }}
                            className="flex-1 min-w-24 accent-indigo-500"
                          />
                          <span className="w-20 text-right text-[10px] text-slate-400 tabular-nums">
                            {isPreviewing
                              ? `${formatAudioTime(previewCurrentTime)} / ${formatAudioTime(previewDuration)}`
                              : '--:-- / --:--'}
                          </span>
                          <audio
                            ref={(el) => {
                              previewAudioRefs.current[t.id] = el
                            }}
                            preload="metadata"
                            src={t.url}
                            onLoadedMetadata={(e) => {
                              if (previewTrackId === t.id) {
                                setPreviewDuration(e.currentTarget.duration || 0)
                              }
                            }}
                            onTimeUpdate={(e) => {
                              if (previewTrackId !== t.id) return
                              setPreviewCurrentTime(e.currentTarget.currentTime || 0)
                            }}
                            onPlay={(e) => {
                              if (previewTrackId && previewTrackId !== t.id) {
                                previewAudioRefs.current[previewTrackId]?.pause()
                              }
                              setPreviewTrackId(t.id)
                              setPreviewDuration(e.currentTarget.duration || 0)
                            }}
                            onPause={() => {
                              if (previewTrackId === t.id) setPreviewTrackId(null)
                            }}
                            onEnded={() => {
                              if (previewTrackId === t.id) {
                                setPreviewTrackId(null)
                                setPreviewCurrentTime(0)
                              }
                            }}
                            className="hidden"
                          />
                        </div>
                      </div>
                    )
                    })}
                  </div>
                  {filteredBgmTracks.length === 0 ? (
                    <p className="text-xs text-slate-500">未找到匹配的 BGM，请换个关键词。</p>
                  ) : null}
                </div>
              )}
            </div>
            <div className="rounded-xl border border-slate-700/70 bg-slate-950/50 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs text-slate-400">时间轴片段（留空则按顺序自动循环整条时间轴）</p>
                <button
                  type="button"
                  onClick={onAddManualBgmTimelineSegment}
                  className="text-xs px-2 py-1 rounded border border-slate-700 text-slate-300 hover:border-slate-500"
                >
                  添加片段
                </button>
              </div>
              {manualBgmTimelineSegments.length === 0 ? (
                <p className="text-xs text-slate-500">未设置片段：导出时会自动按所选 BGM 顺序循环。</p>
              ) : (
                <div className="space-y-1.5">
                  {manualBgmTimelineSegments.map((seg) => (
                    <div key={seg.id} className="grid grid-cols-12 gap-2 items-center">
                      <input
                        type="number"
                        step={0.1}
                        min={0}
                        value={seg.startSec}
                        onChange={(e) => onUpdateManualBgmTimelineSegment(seg.id, { startSec: Number(e.target.value) })}
                        className="col-span-2 rounded bg-slate-900 border border-slate-700 px-2 py-1 text-xs text-slate-200"
                        placeholder="开始(s)"
                      />
                      <input
                        type="number"
                        step={0.1}
                        min={0.1}
                        value={seg.endSec}
                        onChange={(e) => onUpdateManualBgmTimelineSegment(seg.id, { endSec: Number(e.target.value) })}
                        className="col-span-2 rounded bg-slate-900 border border-slate-700 px-2 py-1 text-xs text-slate-200"
                        placeholder="结束(s)"
                      />
                      <select
                        value={seg.trackId ?? ''}
                        onChange={(e) => onUpdateManualBgmTimelineSegment(seg.id, { trackId: e.target.value || undefined })}
                        className="col-span-4 rounded bg-slate-900 border border-slate-700 px-2 py-1 text-xs text-slate-200"
                      >
                        <option value="">自动循环</option>
                        {selectedManualBgmTrackIds.map((trackId) => (
                          <option key={trackId} value={trackId}>{trackId}</option>
                        ))}
                      </select>
                      <input
                        type="number"
                        step={0.5}
                        min={-40}
                        max={12}
                        value={seg.volumeDb ?? ''}
                        onChange={(e) =>
                          onUpdateManualBgmTimelineSegment(seg.id, {
                            volumeDb: e.target.value === '' ? undefined : Number(e.target.value),
                          })
                        }
                        className="col-span-2 rounded bg-slate-900 border border-slate-700 px-2 py-1 text-xs text-slate-200"
                        placeholder="音量dB"
                      />
                      <button
                        type="button"
                        onClick={() => onRemoveManualBgmTimelineSegment(seg.id)}
                        className="col-span-2 text-xs rounded border border-slate-700 px-2 py-1 text-slate-400 hover:text-red-300 hover:border-red-400/40"
                      >
                        删除
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </section>
      <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
          <SplitSquareHorizontal className="w-4 h-4 text-slate-500" />
          批量拆分文案
        </p>
        <textarea
          value={globalQuery}
          onChange={(e) => onGlobalQueryChange(e.target.value)}
          placeholder="粘贴完整文案，按空行自动拆分为多段分别匹配..."
          rows={4}
          className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm outline-none focus:border-indigo-500 placeholder-slate-600 resize-none"
        />
        <div className="flex items-center gap-3">
          <button
            onClick={onSplit}
            disabled={!globalQuery.trim()}
            className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-sm flex items-center gap-2 border border-slate-700 transition-colors"
          >
            <SplitSquareHorizontal className="w-4 h-4" />
            拆分为段落
          </button>
          {segments.length > 0 && (
            <button
              onClick={onMatchAll}
              disabled={globalMatching}
              className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm flex items-center gap-2 transition-colors"
            >
              {globalMatching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              {globalMatching ? '全部匹配中...' : '全部匹配'}
            </button>
          )}
          <button
            onClick={onAddSegment}
            className="ml-auto px-3 py-2 rounded-xl border border-slate-700 bg-slate-800/40 hover:border-slate-500 text-xs text-slate-400 flex items-center gap-1.5 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            手动添加段落
          </button>
        </div>
      </section>
      {segments.length > 0 && (
        <section className="space-y-4">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
              文案段落 · {segments.length} 段
              <span className="ml-2 font-normal normal-case text-slate-600 hidden sm:inline">可拖拽排序，或用每段标题栏箭头</span>
            </p>
            <button onClick={onClearAll} className="text-xs text-slate-600 hover:text-red-400 transition-colors">
              清空全部
            </button>
          </div>
          {segments.map((seg, i) => (
            <div
              key={seg.id}
              className={[
                'rounded-2xl transition-[opacity,box-shadow] duration-200',
                draggingId === seg.id ? 'opacity-45' : '',
                draggingId && draggingId !== seg.id && dropTargetId === seg.id
                  ? 'ring-2 ring-indigo-400/90 shadow-[0_0_0_1px_rgba(129,140,248,0.35),0_8px_28px_-6px_rgba(99,102,241,0.45)]'
                  : '',
                flashId === seg.id
                  ? 'ring-2 ring-emerald-400 shadow-[0_0_24px_-4px_rgba(52,211,153,0.55)]'
                  : '',
              ].join(' ')}
              onDragOver={(e) => {
                if (!draggingId || draggingId === seg.id) return
                e.preventDefault()
                e.dataTransfer.dropEffect = 'move'
                setDropTargetId(seg.id)
              }}
              onDragLeave={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node)) setDropTargetId(null)
              }}
              onDrop={(e) => {
                e.preventDefault()
                const fromId = e.dataTransfer.getData(dragMime) || e.dataTransfer.getData('text/plain')
                setDropTargetId(null)
                setDraggingId(null)
                if (!fromId || fromId === seg.id) return
                onMoveSegment(fromId, seg.id)
                flashRow(fromId)
              }}
            >
              <SegmentRow
                seg={seg}
                index={i}
                segmentCount={segments.length}
                onReorder={(action) => {
                  onSegmentReorder(seg.id, action)
                  flashRow(seg.id)
                }}
                onTextChange={(text) => onSegmentTextChange(seg.id, text)}
                onRemove={() => onRemoveSegment(seg.id)}
                onMatch={() => onMatchSegment(seg.id)}
                onToggleSelect={(clipId) => onToggleClipSelected(seg.id, clipId)}
                onTts={() => onSynthesiseTts(seg.id)}
                onPlayAudio={() => onPlayAudio(seg.id)}
                onStopAudio={onStopAudio}
                onSeekAudio={onSeekAudio ? (t) => onSeekAudio(seg.id, t) : undefined}
                playingAudio={playingSegId === seg.id}
                audioCurrentTime={playingSegId === seg.id ? audioCurrentTime : 0}
                audioDuration={playingSegId === seg.id ? audioDuration : 0}
                onPreview={onPreview}
                onToggleExpand={() => onToggleExpand(seg.id)}
                onOpenClipInOut={onOpenClipInOut ? () => onOpenClipInOut(seg.id) : undefined}
                dragHandleProps={{
                  draggable: true,
                  onDragStart: (e) => {
                    e.dataTransfer.setData(dragMime, seg.id)
                    e.dataTransfer.setData('text/plain', seg.id)
                    e.dataTransfer.effectAllowed = 'move'
                    setDraggingId(seg.id)
                    setDropTargetId(null)
                  },
                  onDragEnd: () => {
                    setDraggingId(null)
                    setDropTargetId(null)
                  },
                }}
              />
            </div>
          ))}
        </section>
      )}
    </>
  )
}
