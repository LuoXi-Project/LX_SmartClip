'use client'

import { useEffect, useRef, useState } from 'react'
import { Loader2, Plus, Search, SplitSquareHorizontal } from 'lucide-react'
import { type MatchClip } from '@/lib/api'
import { type Segment } from './types'
import { CopyGeneratorPanel } from './CopyGeneratorPanel'
import { SegmentRow } from './SegmentRow'

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
}: ManualMatchPanelProps) {
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dropTargetId, setDropTargetId] = useState<string | null>(null)
  const [flashId, setFlashId] = useState<string | null>(null)
  const flashClearRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const dragMime = 'application/x-smartclip-seg-id'

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
