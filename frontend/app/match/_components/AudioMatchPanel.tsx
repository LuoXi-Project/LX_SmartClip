'use client'

import { useRef, useState, type ChangeEvent, type MouseEvent, type ReactNode } from 'react'
import {
  Headphones,
  Loader2,
  Play,
  Scissors,
  Search,
  SplitSquareHorizontal,
  Upload,
  Film,
} from 'lucide-react'
import { type BgmTrack, type MatchClip } from '@/lib/api'
import { type Segment } from './types'
import { SegmentRow } from './SegmentRow'
import { BgmCustomConfigPanel } from './BgmCustomConfigPanel'
import { AudioMatchTimelineModal } from './AudioMatchTimelineModal'
import { fmt } from './types'

export type AudioMatchSource = {
  sourceFilename: string
  durationSec: number
  fullText: string
}

export type AudioMatchPanelProps = {
  topK: number
  topN: number
  onTopKChange: (value: number) => void
  onTopNChange: (value: number) => void
  selectedVideoIds: string[]
  scopeVideoNames: string[]
  audioSource: AudioMatchSource | null
  transcribing: boolean
  transcribeError: string
  onUploadTranscribe: (file: File) => void
  onApplyAsrSegments: (mergeBySentence: boolean) => void
  onSyncAllAudioSlices: () => void
  onSyncSegmentAudio: (segId: string) => void
  syncingAudio: boolean
  globalQuery: string
  onGlobalQueryChange: (value: string) => void
  onSplit: () => void
  onMatchAll: () => void
  globalMatching: boolean
  segments: Segment[]
  onClearAll: () => void
  onSegmentTextChange: (segId: string, text: string) => void
  onMatchSegment: (segId: string) => void
  onToggleClipSelected: (segId: string, clipId: string, e: MouseEvent) => void
  onPlayAudio: (segId: string) => void
  onStopAudio: () => void
  onSeekAudio?: (segId: string, timeSeconds: number) => void
  playingSegId: string | null
  audioCurrentTime?: number
  audioDuration?: number
  onPreview: (clip: MatchClip) => void
  onToggleExpand: (segId: string) => void
  onOpenClipInOut?: (segId: string) => void
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
  /** 保存时间轴微调并重新切片 */
  onTimelineSave: (next: Segment[]) => void | Promise<void>
  timelineSaving?: boolean
  /** 主工作区：成片时间轴（预览 + 裁剪） */
  timelineWorkspace?: ReactNode
  focusedSegId?: string | null
}

export function AudioMatchPanel({
  topK,
  topN,
  onTopKChange,
  onTopNChange,
  selectedVideoIds,
  scopeVideoNames,
  audioSource,
  transcribing,
  transcribeError,
  onUploadTranscribe,
  onApplyAsrSegments,
  onSyncAllAudioSlices,
  onSyncSegmentAudio,
  syncingAudio,
  globalQuery,
  onGlobalQueryChange,
  onSplit,
  onMatchAll,
  globalMatching,
  segments,
  onClearAll,
  onSegmentTextChange,
  onMatchSegment,
  onToggleClipSelected,
  onPlayAudio,
  onStopAudio,
  onSeekAudio,
  playingSegId,
  audioCurrentTime = 0,
  audioDuration = 0,
  onPreview,
  onToggleExpand,
  onOpenClipInOut,
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
  onTimelineSave,
  timelineSaving = false,
  timelineWorkspace,
  focusedSegId,
}: AudioMatchPanelProps) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [timelineOpen, setTimelineOpen] = useState(false)
  const [timelineFocusSegId, setTimelineFocusSegId] = useState<string | null>(null)

  const canOpenTimeline =
    !!audioSource &&
    segments.some(
      (s) => s.audioStartSec != null && s.audioEndSec != null && s.audioEndSec > s.audioStartSec,
    )

  const openTimeline = (segId?: string) => {
    setTimelineFocusSegId(segId ?? null)
    setTimelineOpen(true)
  }

  const matchedCount = segments.filter((s) => s.clips.length > 0).length

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) onUploadTranscribe(f)
    e.target.value = ''
  }

  return (
    <>
      <div className="rounded-2xl border border-rose-500/25 bg-rose-500/5 px-4 py-3 text-xs text-slate-300 leading-relaxed">
        <p className="font-medium text-rose-200 flex items-center gap-2 mb-1">
          <Headphones className="w-4 h-4 shrink-0" />
          音频匹配素材成片
        </p>
        <p>
          上传<strong className="text-slate-200">已做好的配音</strong>，系统自动识别文案与时间轴；再按句检索视频素材、勾选拼接，最终以
          <strong className="text-slate-200">原配音为底</strong>导出成片（无需 TTS）。流程与手动匹配一致，仅文案来源改为 ASR。
        </p>
      </div>

      <section
        className={`rounded-xl border px-4 py-3 text-xs ${
          selectedVideoIds.length > 0
            ? 'border-rose-500/30 bg-rose-500/5 text-slate-300'
            : 'border-amber-600/35 bg-amber-500/5 text-amber-100/90'
        }`}
      >
        <p className="font-medium flex items-center gap-2 mb-1">
          <Film className="w-3.5 h-3.5 shrink-0" />
          检索范围
        </p>
        {selectedVideoIds.length > 0 ? (
          <p className="leading-relaxed">
            仅在已选的 <strong className="text-rose-200">{selectedVideoIds.length}</strong> 个视频内匹配素材：
            <span className="text-slate-400">
              {scopeVideoNames.slice(0, 4).join('、')}
              {scopeVideoNames.length > 4 ? ` 等 ${scopeVideoNames.length} 个` : ''}
            </span>
          </p>
        ) : (
          <p className="leading-relaxed">
            请先在上方<strong className="text-amber-200">「限定视频范围」</strong>勾选要检索的素材；未勾选时不会在全库中检索。
          </p>
        )}
      </section>

      {/* 检索参数：低频调参项，默认折叠 */}
      <details className="rounded-xl border border-slate-800 bg-slate-900/40">
        <summary className="cursor-pointer list-none px-4 py-2.5 flex items-center justify-between gap-3 select-none">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">检索参数（高级）</span>
          <span className="text-[11px] text-slate-500">初筛 {topK} · 推荐 {topN} ▾</span>
        </summary>
        <div className="px-4 pb-4">
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
            <span className="text-[11px] text-slate-600">初筛=每段召回的候选数；推荐=每段展示的片段数</span>
          </div>
        </div>
      </details>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">① 上传配音并识别</p>
        <input
          ref={fileRef}
          type="file"
          accept="audio/*,video/*,.mp3,.wav,.m4a,.aac,.flac,.ogg,.webm"
          className="hidden"
          onChange={onFileChange}
        />
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={transcribing}
            onClick={() => fileRef.current?.click()}
            className="px-4 py-2.5 rounded-xl bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-sm font-medium flex items-center gap-2 transition-colors"
          >
            {transcribing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            {transcribing ? '识别中…' : audioSource ? '重新上传配音' : '选择配音文件'}
          </button>
          {audioSource ? (
            <span className="text-xs text-slate-400 tabular-nums">
              时长 {fmt(audioSource.durationSec)}
              {audioSource.fullText ? ` · 共 ${audioSource.fullText.length} 字` : ''}
            </span>
          ) : null}
        </div>
        {transcribeError ? <p className="text-xs text-red-400">{transcribeError}</p> : null}
        {audioSource && globalQuery.trim() ? (
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              onClick={() => onApplyAsrSegments(false)}
              className="px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800/60 text-xs text-slate-200 hover:border-rose-500/40 transition-colors"
            >
              按 ASR 句段生成段落
            </button>
            <button
              type="button"
              onClick={() => onApplyAsrSegments(true)}
              className="px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800/60 text-xs text-slate-200 hover:border-rose-500/40 transition-colors"
            >
              合并为完整句再分段
            </button>
          </div>
        ) : null}
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">② 文案校对与拆段</p>
        <textarea
          value={globalQuery}
          onChange={(e) => onGlobalQueryChange(e.target.value)}
          placeholder={audioSource ? 'ASR 全文将显示在此，可编辑后按空行或句号拆段…' : '请先上传配音并完成识别…'}
          rows={4}
          disabled={!audioSource}
          className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm outline-none focus:border-rose-500 placeholder-slate-600 resize-none disabled:opacity-50"
        />
        <div className="flex items-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={onSplit}
            disabled={!globalQuery.trim() || !audioSource}
            className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-sm flex items-center gap-2 border border-slate-700 transition-colors"
          >
            <SplitSquareHorizontal className="w-4 h-4" />
            拆分为段落
          </button>
          {segments.length > 0 && (
            <span className="text-[11px] text-slate-600">拆分后请在下方逐段匹配素材</span>
          )}
        </div>
      </section>

      {/* ③ 段落与素材：批量操作与列表合一（与手动模式同构） */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
              <SplitSquareHorizontal className="w-4 h-4 text-slate-500" />
              段落与素材
            </p>
            {segments.length > 0 && (
              <span className="text-[11px] text-slate-500 whitespace-nowrap">
                {segments.length} 段 · {matchedCount} 已匹配
              </span>
            )}
          </div>
          {segments.length > 0 && (
            <div className="flex items-center gap-3">
              {canOpenTimeline ? (
                <button
                  type="button"
                  onClick={() => openTimeline()}
                  className="text-xs text-rose-300/90 hover:text-rose-200 flex items-center gap-1 transition-colors"
                >
                  <Scissors className="w-3.5 h-3.5" />
                  底音频时间轴
                </button>
              ) : null}
              <button type="button" onClick={onClearAll} className="text-xs text-slate-600 hover:text-red-400 transition-colors">
                清空全部
              </button>
            </div>
          )}
        </div>
        {segments.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={onMatchAll}
              disabled={globalMatching || syncingAudio || selectedVideoIds.length === 0}
              title={selectedVideoIds.length === 0 ? '请先在上方限定视频范围' : undefined}
              className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm flex items-center gap-2 transition-colors"
            >
              {globalMatching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              {globalMatching ? '全部匹配中…' : '全部匹配素材'}
            </button>
            <button
              type="button"
              onClick={onSyncAllAudioSlices}
              disabled={syncingAudio || globalMatching || !audioSource}
              className="px-4 py-2 rounded-xl bg-rose-700 hover:bg-rose-600 disabled:opacity-50 text-sm flex items-center gap-2 transition-colors"
            >
              {syncingAudio ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {syncingAudio ? '原声切片中…' : '同步全部原声'}
            </button>
          </div>
        )}
        {segments.length === 0 ? (
          <p className="text-[11px] text-slate-600 leading-relaxed">
            上传配音识别并拆段后，在此逐段匹配素材；成片以原配音为底，无需 TTS。
          </p>
        ) : (
          <p className="text-[11px] text-slate-600 hidden sm:block">
            素材选择与文案；成片预览请用下方时间轴，底音频对齐请用「底音频时间轴」。
          </p>
        )}
        {segments.length > 0 && (
          <div className="space-y-4 pt-1">
            {segments.map((seg, i) => (
              <div
                key={seg.id}
                id={`seg-card-${seg.id}`}
                className={[
                  'scroll-mt-24 rounded-2xl transition-shadow duration-200',
                  focusedSegId === seg.id
                    ? 'ring-2 ring-indigo-400/80 shadow-[0_0_20px_-6px_rgba(99,102,241,0.45)]'
                    : '',
                ].join(' ')}
              >
                <SegmentRow
                  seg={seg}
                  index={i}
                  segmentCount={segments.length}
                  audioMatchMode
                  onTextChange={(text) => onSegmentTextChange(seg.id, text)}
                  onMatch={() => onMatchSegment(seg.id)}
                  onToggleSelect={(clipId, e) => onToggleClipSelected(seg.id, clipId, e)}
                  onTts={() => {}}
                  onSyncAudio={() => onSyncSegmentAudio(seg.id)}
                  syncingAudio={syncingAudio}
                  onPlayAudio={() => onPlayAudio(seg.id)}
                  onStopAudio={onStopAudio}
                  onSeekAudio={onSeekAudio ? (t) => onSeekAudio(seg.id, t) : undefined}
                  playingAudio={playingSegId === seg.id}
                  audioCurrentTime={playingSegId === seg.id ? audioCurrentTime : 0}
                  audioDuration={playingSegId === seg.id ? audioDuration : 0}
                  onPreview={onPreview}
                  onToggleExpand={() => onToggleExpand(seg.id)}
                  onOpenClipInOut={onOpenClipInOut ? () => onOpenClipInOut(seg.id) : undefined}
                  onOpenAudioTimeline={() => openTimeline(seg.id)}
                />
              </div>
            ))}
          </div>
        )}
      </section>
      {timelineWorkspace}
      {/* 成片 BGM：导出期参数，默认折叠（与手动模式一致） */}
      <details className="group rounded-2xl border border-slate-800 bg-slate-900/40">
        <summary className="cursor-pointer list-none px-4 py-3 flex items-center justify-between gap-3 select-none">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
            成片 BGM{manualBgmEnabled && <span className="ml-2 text-emerald-400 normal-case font-normal">已启用 · {selectedManualBgmTrackIds.length} 首</span>}
          </span>
          <span className="text-[11px] text-slate-500 group-open:hidden">
            {manualBgmEnabled ? '调整曲目与分段 ▾' : '导出时混入背景音乐（可选）▾'}
          </span>
          <span className="text-[11px] text-slate-500 hidden group-open:inline">收起 ▴</span>
        </summary>
        <div className="px-4 pb-4 space-y-3">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={manualBgmEnabled}
              onChange={(e) => onManualBgmEnabledChange(e.target.checked)}
              className="rounded border-slate-600 bg-slate-900 text-emerald-500 focus:ring-emerald-500/40"
            />
            <span className="text-sm text-slate-200">导出时混入 BGM（与手动匹配一致）</span>
          </label>
          {manualBgmEnabled && (
            <BgmCustomConfigPanel
              title="手动 BGM 自定义"
              enabled
              onEnabledChange={() => {}}
              bgmTracks={bgmTracks}
              bgmListError={bgmListError}
              selectedTrackIds={selectedManualBgmTrackIds}
              onToggleTrack={onToggleManualBgmTrack}
              volumeByTrackId={manualBgmVolumeByTrackId}
              onTrackVolumeChange={onManualBgmTrackVolumeChange}
              timelineSegments={manualBgmTimelineSegments}
              onAddTimelineSegment={onAddManualBgmTimelineSegment}
              onRemoveTimelineSegment={onRemoveManualBgmTimelineSegment}
              onUpdateTimelineSegment={onUpdateManualBgmTimelineSegment}
            />
          )}
        </div>
      </details>

      {audioSource && (
        <AudioMatchTimelineModal
          open={timelineOpen}
          onClose={() => setTimelineOpen(false)}
          segments={segments}
          sourceFilename={audioSource.sourceFilename}
          sourceDurationSec={audioSource.durationSec}
          initialSegId={timelineFocusSegId}
          saving={timelineSaving}
          onSave={async (next) => {
            await onTimelineSave(next)
            setTimelineOpen(false)
          }}
        />
      )}
    </>
  )
}
