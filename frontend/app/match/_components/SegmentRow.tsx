import type { HTMLAttributes } from 'react'
import {
  ChevronDown,
  ChevronUp,
  ChevronsDown,
  ChevronsUp,
  GripVertical,
  Loader2,
  Mic,
  MicOff,
  Play,
  Search,
  Trash2,
  Volume2,
} from 'lucide-react'
import type { MatchClip } from '@/lib/api'
import type { Segment } from './types'
import { ClipCard } from './ClipCard'

export function SegmentRow({
  seg, index, segmentCount = 0, onReorder,
  onTextChange, onRemove, onMatch, onToggleSelect,
  onTts, onPlayAudio, onStopAudio, playingAudio, onPreview, onToggleExpand,
  dragHandleProps,
}: {
  seg: Segment; index: number
  /** 段落总数，与 onReorder 一起用于禁用边界按钮 */
  segmentCount?: number
  onReorder?: (action: 'up' | 'down' | 'top' | 'bottom') => void
  onTextChange: (t: string) => void
  onRemove: () => void
  onMatch: () => void
  onToggleSelect: (clipId: string) => void
  onTts: () => void
  onPlayAudio: () => void
  onStopAudio: () => void
  playingAudio: boolean
  onPreview: (clip: MatchClip) => void
  onToggleExpand: () => void
  /** 拖动手柄（仅手动匹配段落排序） */
  dragHandleProps?: HTMLAttributes<HTMLDivElement> & { draggable?: boolean }
}) {
  const canUp = index > 0
  const canDown = segmentCount > 0 && index < segmentCount - 1
  const primaryId = seg.selectedClipIds?.[0] ?? ''
  const chosen = primaryId ? (seg.clips.find((c) => c.clip_id === primaryId) ?? null) : null
  const selectedCount = seg.selectedClipIds?.length ?? 0
  const orderIndexOf = (clipId: string) => (seg.selectedClipIds?.indexOf(clipId) ?? -1)

  return (
    <div className="rounded-2xl border border-slate-800 bg-[#0e1017] overflow-hidden">
      {/* header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-slate-900/60 border-b border-slate-800">
        {dragHandleProps ? (
          <div
            role="button"
            tabIndex={0}
            title="拖动排序"
            aria-label="拖动排序"
            className="shrink-0 p-0.5 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 cursor-grab active:cursor-grabbing touch-none select-none"
            {...dragHandleProps}
          >
            <GripVertical className="w-4 h-4" />
          </div>
        ) : null}
        <div className="w-6 h-6 rounded-lg bg-indigo-500/20 text-indigo-300 text-xs font-bold flex items-center justify-center shrink-0">
          {index + 1}
        </div>
        <span className="text-xs text-slate-400 font-medium">段落 {index + 1}</span>
        <div className="flex-1" />
        {selectedCount > 0 && (
          <span className="text-[10px] text-emerald-500 bg-emerald-500/10 border border-emerald-500/20 rounded-full px-2 py-0.5">
            已选 {selectedCount} 个
          </span>
        )}
        {seg.ttsFilename && (
          <span className="text-[10px] text-violet-400 bg-violet-500/10 border border-violet-500/20 rounded-full px-2 py-0.5">
            配音就绪
          </span>
        )}
        {onReorder && segmentCount > 1 ? (
          <div className="flex items-center gap-0.5 shrink-0 rounded-lg border border-slate-700/80 bg-slate-900/50 p-0.5">
            <button
              type="button"
              title="移至顶部"
              disabled={!canUp}
              onClick={() => onReorder('top')}
              className="p-1 rounded-md text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-25 disabled:hover:bg-transparent transition-colors"
            >
              <ChevronsUp className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              title="上移"
              disabled={!canUp}
              onClick={() => onReorder('up')}
              className="p-1 rounded-md text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-25 disabled:hover:bg-transparent transition-colors"
            >
              <ChevronUp className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              title="下移"
              disabled={!canDown}
              onClick={() => onReorder('down')}
              className="p-1 rounded-md text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-25 disabled:hover:bg-transparent transition-colors"
            >
              <ChevronDown className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              title="移至底部"
              disabled={!canDown}
              onClick={() => onReorder('bottom')}
              className="p-1 rounded-md text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-25 disabled:hover:bg-transparent transition-colors"
            >
              <ChevronsDown className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : null}
        <button onClick={onToggleExpand} className="text-slate-600 hover:text-slate-300 transition-colors">
          {seg.expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        <button onClick={onRemove} className="text-slate-700 hover:text-red-400 transition-colors">
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      <div className="px-4 py-4 space-y-4">
        {/* text + match */}
        <div className="flex gap-2">
          <textarea
            value={seg.text}
            onChange={(e) => onTextChange(e.target.value)}
            placeholder="输入该段文案..."
            rows={2}
            className="flex-1 rounded-xl bg-slate-900/60 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 resize-none placeholder-slate-600"
          />
          <button
            onClick={onMatch}
            disabled={!seg.text.trim() || seg.matchLoading}
            className="shrink-0 px-3 py-2 h-fit rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-sm font-medium flex items-center gap-1.5 mt-0.5 transition-colors"
          >
            {seg.matchLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            {seg.matchLoading ? '匹配中' : '匹配'}
          </button>
        </div>
        {seg.matchError && <p className="text-xs text-red-400">{seg.matchError}</p>}

        {/* candidates */}
        {seg.clips.length > 0 && (
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-2.5">
              候选视频 · {seg.clips.length} 个
              <span className="normal-case font-normal ml-1 text-slate-600">— 点击勾选序号</span>
            </p>
            <div className="flex gap-3 overflow-x-auto pb-2">
              {seg.clips.map((clip, ci) => (
                <ClipCard
                  key={clip.clip_id}
                  clip={clip}
                  chosen={clip.clip_id === primaryId || (primaryId === '' && seg.chosenIdx === ci)}
                  order={(() => {
                    const idx = orderIndexOf(clip.clip_id)
                    return idx >= 0 ? idx + 1 : undefined
                  })()}
                  onChoose={() => onToggleSelect(clip.clip_id)}
                  onPreview={() => onPreview(clip)}
                />
              ))}
            </div>
          </div>
        )}

        {/* TTS bar — only when a clip is chosen */}
        {chosen && (
          <div className="flex items-center gap-3 rounded-xl bg-slate-900/40 border border-slate-800 px-3 py-2.5">
            <Volume2 className="w-4 h-4 text-slate-500 shrink-0" />
            <div className="flex-1 min-w-0">
              {seg.ttsError && !seg.ttsFilename
                ? <p className="text-xs text-red-400 truncate">{seg.ttsError}</p>
                : seg.ttsFilename
                  ? <p className="text-xs text-emerald-400 font-medium">✓ 配音已合成</p>
                  : <p className="text-xs text-slate-500">尚未合成配音</p>}
            </div>
            {seg.ttsFilename && (
              playingAudio
                ? (
                  <button onClick={onStopAudio} className="shrink-0 px-2.5 py-1 rounded-lg bg-violet-500/20 text-violet-300 text-xs flex items-center gap-1 hover:bg-violet-500/30 transition-colors">
                    <MicOff className="w-3.5 h-3.5" /> 停止
                  </button>
                ) : (
                  <button onClick={onPlayAudio} className="shrink-0 px-2.5 py-1 rounded-lg bg-slate-800 text-slate-300 text-xs flex items-center gap-1 hover:bg-slate-700 transition-colors">
                    <Play className="w-3.5 h-3.5" /> 试听
                  </button>
                )
            )}
            <button
              onClick={onTts}
              disabled={seg.ttsLoading || !seg.text.trim()}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:bg-slate-800 disabled:text-slate-600 text-xs text-white font-medium flex items-center gap-1.5 transition-colors"
            >
              {seg.ttsLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Mic className="w-3.5 h-3.5" />}
              {seg.ttsLoading ? '合成中' : seg.ttsFilename ? '重新合成' : '合成配音'}
            </button>
          </div>
        )}

        {/* expanded detail */}
        {seg.expanded && chosen && (chosen.asr_text || chosen.vlm_description) && (
          <div className="rounded-xl bg-slate-900/30 border border-slate-800 px-3 py-3 space-y-2">
            {chosen.asr_text && (
              <div>
                <p className="text-[10px] text-slate-600 uppercase tracking-widest mb-1">台词</p>
                <p className="text-xs text-slate-300 leading-relaxed">{chosen.asr_text}</p>
              </div>
            )}
            {chosen.vlm_description && (
              <div>
                <p className="text-[10px] text-slate-600 uppercase tracking-widest mb-1">画面描述</p>
                <p className="text-xs text-slate-300 leading-relaxed">{chosen.vlm_description}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
