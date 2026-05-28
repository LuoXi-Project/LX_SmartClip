import type { HTMLAttributes, MouseEvent } from 'react'
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
  Scissors,
  Search,
  Trash2,
  Volume2,
} from 'lucide-react'
import type { MatchClip } from '@/lib/api'
import type { Segment } from './types'
import { trimIsCustomForSlot } from './clipTrim'
import { ClipCard } from './ClipCard'
import { orderPositionsForKey } from '@/lib/match/orderedSelection'

export function SegmentRow({
  seg, index, segmentCount = 0, onReorder,
  onTextChange, onRemove, onMatch, onToggleSelect,
  onTts,
  onPlayAudio,
  onStopAudio,
  onSeekAudio,
  playingAudio,
  audioCurrentTime = 0,
  audioDuration = 0,
  onPreview,
  onToggleExpand,
  onOpenClipInOut,
  dragHandleProps,
  audioMatchMode = false,
  onSyncAudio,
  syncingAudio = false,
  onOpenAudioTimeline,
}: {
  seg: Segment; index: number
  /** 段落总数，与 onReorder 一起用于禁用边界按钮 */
  segmentCount?: number
  onReorder?: (action: 'up' | 'down' | 'top' | 'bottom') => void
  onTextChange: (t: string) => void
  /** 未提供时不显示删除（如音频匹配：段落与底音频时间轴绑定） */
  onRemove?: () => void
  onMatch: () => void
  onToggleSelect: (clipId: string, e: MouseEvent) => void
  onTts: () => void
  onPlayAudio: () => void
  onStopAudio: () => void
  onSeekAudio?: (timeSeconds: number) => void
  playingAudio: boolean
  audioCurrentTime?: number
  audioDuration?: number
  onPreview: (clip: MatchClip) => void
  onToggleExpand: () => void
  /** 打开主选素材出入点（单选时可用） */
  onOpenClipInOut?: () => void
  /** 拖动手柄（仅手动匹配段落排序） */
  dragHandleProps?: HTMLAttributes<HTMLDivElement> & { draggable?: boolean }
  /** 音频匹配模式：使用上传配音切片，隐藏 TTS */
  audioMatchMode?: boolean
  onSyncAudio?: () => void
  syncingAudio?: boolean
  /** 音频匹配：打开底音频时间轴剪辑台 */
  onOpenAudioTimeline?: () => void
}) {
  const canUp = index > 0
  const canDown = segmentCount > 0 && index < segmentCount - 1
  const primaryId = seg.selectedClipIds?.[0] ?? ''
  const chosen = primaryId ? (seg.clips.find((c) => c.clip_id === primaryId) ?? null) : null
  const trimCustom = (seg.selectedClipIds ?? []).some((id, slotIdx) => {
    const c = seg.clips.find((x) => x.clip_id === id)
    return c ? trimIsCustomForSlot(seg, c, slotIdx) : false
  })
  const selectedCount = seg.selectedClipIds?.length ?? 0

  const fmtTime = (s: number) => {
    if (!Number.isFinite(s) || s < 0) return '0:00'
    const m = Math.floor(s / 60)
    const ss = Math.floor(s % 60).toString().padStart(2, '0')
    return `${m}:${ss}`
  }

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
          audioMatchMode && onOpenAudioTimeline ? (
            <button
              type="button"
              onClick={onOpenAudioTimeline}
              title="打开底音频时间轴微调"
              className="text-[10px] rounded-full px-2 py-0.5 border text-rose-300 bg-rose-500/10 border-rose-500/20 hover:bg-rose-500/20 transition-colors"
            >
              原声就绪
            </button>
          ) : (
            <span
              className={`text-[10px] rounded-full px-2 py-0.5 border ${
                audioMatchMode
                  ? 'text-rose-300 bg-rose-500/10 border-rose-500/20'
                  : 'text-violet-400 bg-violet-500/10 border-violet-500/20'
              }`}
            >
              {audioMatchMode ? '原声就绪' : '配音就绪'}
            </span>
          )
        )}
        {audioMatchMode &&
          seg.audioStartSec != null &&
          seg.audioEndSec != null &&
          !seg.ttsFilename && (
            onOpenAudioTimeline ? (
              <button
                type="button"
                onClick={onOpenAudioTimeline}
                title="打开底音频时间轴微调"
                className="text-[10px] text-amber-400/90 bg-amber-500/10 border border-amber-500/20 rounded-full px-2 py-0.5 tabular-nums hover:bg-amber-500/20 transition-colors"
              >
                {fmtTime(seg.audioStartSec)}–{fmtTime(seg.audioEndSec)}
              </button>
            ) : (
              <span className="text-[10px] text-amber-400/90 bg-amber-500/10 border border-amber-500/20 rounded-full px-2 py-0.5 tabular-nums">
                {fmtTime(seg.audioStartSec)}–{fmtTime(seg.audioEndSec)}
              </span>
            )
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
        {onRemove && !audioMatchMode ? (
          <button onClick={onRemove} className="text-slate-700 hover:text-red-400 transition-colors">
            <Trash2 className="w-4 h-4" />
          </button>
        ) : null}
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
              <span className="normal-case font-normal ml-1 text-slate-600">
                — 点击勾选顺序；Shift+点击再叠同一条
              </span>
            </p>
            <div className="flex gap-3 overflow-x-auto pb-2">
              {seg.clips.map((clip) => {
                const ordered = seg.selectedClipIds ?? []
                const positions = orderPositionsForKey(ordered, clip.clip_id)
                const inSelection = positions.length > 0
                return (
                  <ClipCard
                    key={clip.clip_id}
                    clip={clip}
                    chosen={inSelection}
                    orderPositions={positions.length ? positions : undefined}
                    onChoose={(e) => onToggleSelect(clip.clip_id, e)}
                    onPreview={() => onPreview(clip)}
                  />
                )
              })}
            </div>
          </div>
        )}

        {/* TTS bar — only when a clip is chosen */}
        {chosen && onOpenClipInOut && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onOpenClipInOut}
              title="预览并设置各勾选素材的出入点，可在窗口内切换片段"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-slate-600 bg-slate-800/60 text-xs text-slate-200 hover:border-indigo-500/50 hover:bg-slate-800 transition-colors"
            >
              <Scissors className="w-3.5 h-3.5 shrink-0" />
              出入点预览
              {trimCustom ? (
                <span className="text-[10px] font-medium text-amber-400/90">已裁剪</span>
              ) : null}
            </button>
            {(seg.selectedClipIds?.length ?? 0) > 1 ? (
              <span className="text-[10px] text-slate-600">多选时在窗口顶部切换素材分别编辑</span>
            ) : null}
          </div>
        )}
        {(chosen || audioMatchMode) && (
          <div className="flex items-center gap-3 rounded-xl bg-slate-900/40 border border-slate-800 px-3 py-2.5">
            <Volume2 className="w-4 h-4 text-slate-500 shrink-0" />
            <div className="flex-1 min-w-0">
              {seg.ttsError && !seg.ttsFilename
                ? <p className="text-xs text-red-400 truncate">{seg.ttsError}</p>
                : seg.ttsFilename
                  ? (
                    <p className={`text-xs font-medium ${audioMatchMode ? 'text-rose-300' : 'text-emerald-400'}`}>
                      {audioMatchMode ? '✓ 原声切片已就绪' : '✓ 配音已合成'}
                    </p>
                  )
                  : (
                    <p className="text-xs text-slate-500">
                      {audioMatchMode ? '尚未切片原声（请同步原声）' : '尚未合成配音'}
                    </p>
                  )}
            </div>
            {seg.ttsFilename && playingAudio && audioDuration > 0 ? (
              <div className="flex items-center gap-2 shrink-0">
                <span className="hidden sm:inline text-[10px] tabular-nums text-slate-500 w-[72px] text-right">
                  {fmtTime(audioCurrentTime)} / {fmtTime(audioDuration)}
                </span>
                <input
                  type="range"
                  min={0}
                  max={audioDuration}
                  step={0.05}
                  value={Math.min(Math.max(audioCurrentTime, 0), audioDuration)}
                  onChange={(e) => onSeekAudio?.(Number(e.target.value))}
                  className="w-28 sm:w-36 md:w-44 accent-violet-500"
                  aria-label="配音时间轴"
                />
              </div>
            ) : null}
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
            {audioMatchMode ? (
              <>
                {onOpenAudioTimeline &&
                seg.audioStartSec != null &&
                seg.audioEndSec != null ? (
                  <button
                    type="button"
                    onClick={onOpenAudioTimeline}
                    className="shrink-0 px-3 py-1.5 rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-200 text-xs font-medium hover:bg-rose-500/20 transition-colors"
                  >
                    微调时间
                  </button>
                ) : null}
                {onSyncAudio ? (
                  <button
                    type="button"
                    onClick={onSyncAudio}
                    disabled={syncingAudio || seg.audioStartSec == null || seg.audioEndSec == null}
                    className="shrink-0 px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 disabled:bg-slate-800 disabled:text-slate-600 text-xs text-white font-medium flex items-center gap-1.5 transition-colors"
                  >
                    {syncingAudio ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Mic className="w-3.5 h-3.5" />}
                    {syncingAudio ? '切片中' : '刷新切片'}
                  </button>
                ) : null}
              </>
            ) : (
              <button
                onClick={onTts}
                disabled={seg.ttsLoading || !seg.text.trim()}
                className="shrink-0 px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:bg-slate-800 disabled:text-slate-600 text-xs text-white font-medium flex items-center gap-1.5 transition-colors"
              >
                {seg.ttsLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Mic className="w-3.5 h-3.5" />}
                {seg.ttsLoading ? '合成中' : seg.ttsFilename ? '重新合成' : '合成配音'}
              </button>
            )}
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
