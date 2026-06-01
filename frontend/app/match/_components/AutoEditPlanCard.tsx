'use client'

import { Loader2 } from 'lucide-react'
import type { AutoEditPlanApi, AutoJianyingDraftDownloadEntryApi } from '@/lib/api'
import { HoverTruncatedTooltip } from '@/components/ui/hover-truncated-tooltip'
import type { ClipMetaByClip, SelectedPreviewState } from './autoEditTypes'
import { planSegmentPreviewAbsRange } from './planSegmentPreviewRange'
import { fmt } from './types'

export type AutoEditPlanCardProps = {
  p: AutoEditPlanApi
  idx: number
  subtitleEnabled: boolean
  customPlanById: Record<string, AutoEditPlanApi>
  autoExpandedPlanIds: string[]
  onTogglePlanExpand: (planId: string) => void
  expandedPreviewPlanIds: string[]
  togglePreviewExpand: (planId: string) => void
  clipMetaByClip: ClipMetaByClip
  isActive?: boolean
  onSelectPlan: (plan: AutoEditPlanApi, index: number) => void
  onOpenFullscreenPlan: (plan: AutoEditPlanApi, index: number) => void
  onSelectPreview: (next: SelectedPreviewState) => void
  onRealizePlan: (plan: AutoEditPlanApi, index: number) => void
  onExportJianyingDraft: (plan: AutoEditPlanApi, index: number) => void
  autoRealizingId: string | null
  autoJianyingDraftExportingId: string | null
  autoRealizeMsg: string
  autoRealizeDownloads: Record<string, { filename: string; url: string }>
  autoJianyingDraftDownloads: Record<string, AutoJianyingDraftDownloadEntryApi>
}

export function AutoEditPlanCard({
  p,
  idx,
  subtitleEnabled,
  customPlanById,
  autoExpandedPlanIds,
  onTogglePlanExpand,
  expandedPreviewPlanIds,
  togglePreviewExpand,
  clipMetaByClip,
  isActive = false,
  onSelectPlan,
  onOpenFullscreenPlan,
  onSelectPreview,
  onRealizePlan,
  onExportJianyingDraft,
  autoRealizingId,
  autoJianyingDraftExportingId,
  autoRealizeMsg,
  autoRealizeDownloads,
  autoJianyingDraftDownloads,
}: AutoEditPlanCardProps) {
  const planTitle = p.title || `方案 ${idx + 1}`
  const segs = p.segments ?? []
  const activeCount = segs.filter((s) => !s.exclude_from_output).length

  return (
    <div
      className={[
        'rounded-2xl border bg-slate-900/60 p-4 space-y-2 transition-shadow',
        isActive
          ? 'border-cyan-500/50 ring-2 ring-cyan-400/40 shadow-[0_0_24px_-8px_rgba(34,211,238,0.35)]'
          : 'border-slate-800',
      ].join(' ')}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-100 truncate">{planTitle}</p>
          <div className="text-[11px] text-slate-500 mt-0.5">
            模式：{p.mode === 'auto' ? '自动' : p.mode === 'voiceover' ? '配音剪辑' : '原声剪辑'}
            {customPlanById[p.plan_id] != null && (
              <span className="ml-2 inline-flex items-center rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-200">
                已自定义
              </span>
            )}
            {p.bgm != null && (
              <div className="block mt-0.5 text-slate-600">
                方案 BGM：
                {p.bgm.enabled ? (
                  <HoverTruncatedTooltip
                    as="span"
                    clamp={1}
                    text={`${(p.bgm.track_id && String(p.bgm.track_id).trim()) || '自动 / 曲库'}${
                      p.bgm.source ? `（${p.bgm.source}）` : ''
                    }`}
                    tooltipTitle="方案 BGM"
                    anchorClassName="inline-block max-w-[10rem] align-middle"
                  />
                ) : (
                  <span>未启用</span>
                )}
              </div>
            )}
          </div>
        </div>
        <div className="flex-shrink-0 text-right text-[11px] text-slate-500 space-y-0.5">
          {p.target_duration_sec && <p>目标：{p.target_duration_sec.toFixed(3)}s</p>}
          {p.estimated_duration_sec && <p>预估：{p.estimated_duration_sec.toFixed(3)}s</p>}
          <p>
            段落：{activeCount} 段参与成片 / 共 {segs.length} 段
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onSelectPlan(p, idx)}
          className={`text-[11px] rounded-lg border px-2 py-1 transition-colors ${
            isActive
              ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-100'
              : 'border-slate-700 bg-slate-950/40 text-slate-200 hover:bg-slate-950/70'
          }`}
          title="在上方时间轴主工作区编辑此方案"
        >
          {isActive ? '当前编辑中' : '编辑此方案'}
        </button>
        <button
          type="button"
          onClick={() => onOpenFullscreenPlan(p, idx)}
          className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-400 hover:bg-slate-950/70 hover:text-slate-200"
          title="全屏打开剪辑台"
        >
          全屏
        </button>
        {p.segments?.some((s) => s.subtitle?.text?.trim()) && (
          <span className="text-[11px] text-emerald-300/80">含字幕</span>
        )}
      </div>

      {p.summary && (
        <div className="space-y-1">
          <p
            className={`text-xs text-slate-300 ${
              autoExpandedPlanIds.includes(p.plan_id) ? '' : 'line-clamp-3'
            }`}
          >
            {p.summary}
          </p>
          {p.summary.length > 80 && (
            <button
              type="button"
              onClick={() => onTogglePlanExpand(p.plan_id)}
              className="text-[11px] text-cyan-300 hover:text-cyan-200"
            >
              {autoExpandedPlanIds.includes(p.plan_id) ? '收起详情' : '展开详情'}
            </button>
          )}
        </div>
      )}

      <div className="text-[11px] text-slate-500 space-y-1">
        <p>
          输出：
          {p.mode === 'original'
            ? subtitleEnabled
              ? '原声 + 字幕'
              : '原声（无字幕）'
            : subtitleEnabled
              ? '配音 + 字幕'
              : '配音（无字幕）'}
        </p>
        <p>
          片段预览：
          <span className="ml-1 text-slate-600">
            （{activeCount} 段参与成片，共 {segs.length} 段）
          </span>
        </p>
        <div
          className={`mt-1 flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-950/40 px-2 py-2 ${
            expandedPreviewPlanIds.includes(p.plan_id)
              ? 'max-h-none'
              : 'max-h-24 overflow-y-auto'
          }`}
        >
          {segs.map((s) => {
            const excluded = !!s.exclude_from_output
            const clipId = s.selected_clip_ids?.[0] || s.clip_group?.[0]?.clip_id
            const videoId = s.clip_group?.[0]?.video_id || null
            const cm = clipId ? clipMetaByClip[clipId] : undefined

            const { displayStart, displayEnd } = planSegmentPreviewAbsRange(s, cm)
            const planRawStart = Number(s.subtitle?.timing_hint?.start ?? s.start_time_sec) || 0
            const planRawEnd = Number(s.subtitle?.timing_hint?.end ?? s.end_time_sec) || planRawStart
            const usedTimingHint = Boolean(s.subtitle?.timing_hint)
            const canMapByClip = Boolean(
              cm &&
                planRawEnd > planRawStart + 0.05 &&
                planRawStart >= Number(cm.start_time) - 0.05 &&
                planRawEnd <= Number(cm.end_time) + 0.05
            )

            return (
              <button
                key={s.id}
                type="button"
                onClick={() => {
                  if (!clipId) return
                  onSelectPreview({
                    planId: p.plan_id,
                    planTitle,
                    segmentId: s.id,
                    order: s.order,
                    clipId,
                    videoId,
                    source: videoId ? 'video' : 'clip',
                    startSec: displayStart,
                    endSec: displayEnd,
                  })
                }}
                disabled={!clipId}
                className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-900/50 disabled:text-slate-500 ${
                  excluded
                    ? 'border-amber-600/35 bg-amber-950/40 text-amber-200/80 hover:bg-amber-950/55 line-through decoration-amber-500/50'
                    : 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20'
                }`}
                title={
                  clipId
                    ? excluded
                      ? `已弃用：成片不包含本段；仍可预览素材。${
                          cm ? ` ${fmt(displayStart)}–${fmt(displayEnd)}` : ''
                        }`
                      : cm
                        ? (s.clip_trims?.length ?? 0) > 1
                          ? `多段拼接（${s.clip_trims?.length} 条 clip_trims），成片绝对时间窗 ${fmt(displayStart)}–${fmt(displayEnd)}`
                          : canMapByClip || usedTimingHint
                            ? `素材视频绝对时间：${fmt(displayStart)}–${fmt(displayEnd)}（clip 库区间 ${fmt(cm.start_time)}–${fmt(cm.end_time)}）`
                            : `按方案时间窗预览：${fmt(displayStart)}–${fmt(displayEnd)}（clip区间 ${fmt(cm.start_time)}–${fmt(cm.end_time)}）`
                        : `加载库内时间中… 方案标注 ${fmt(planRawStart)}–${fmt(planRawEnd)}`
                    : '该片段缺少 clip_id，暂不可预览'
                }
              >
                #{s.order}
                {excluded ? ' 弃用' : ''}
                {(s.clip_trims?.length ?? 0) > 1 ? ` ·${s.clip_trims?.length}段` : ''}（{fmt(displayStart)}-{fmt(displayEnd)}）
              </button>
            )
          })}
        </div>
        {segs.length > 12 && (
          <button
            type="button"
            onClick={() => togglePreviewExpand(p.plan_id)}
            className="mt-1 text-[11px] text-cyan-300 hover:text-cyan-200"
          >
            {expandedPreviewPlanIds.includes(p.plan_id) ? '折叠列表' : '展开列表'}
          </button>
        )}
      </div>

      <div className="pt-1 space-y-2">
        <button
          onClick={() => onRealizePlan(customPlanById[p.plan_id] ?? p, idx)}
          disabled={
            autoRealizingId !== null || autoJianyingDraftExportingId !== null || activeCount === 0
          }
          title={activeCount === 0 ? '至少保留一段参与成片' : undefined}
          className="w-full inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded-xl border border-emerald-500/50 bg-emerald-500/10 text-[11px] text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-60 transition-colors"
        >
          {autoRealizingId === p.plan_id ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              成片生成中...
            </>
          ) : (
            <>一键成片（MP4）</>
          )}
        </button>
        <button
          type="button"
          onClick={() => onExportJianyingDraft(customPlanById[p.plan_id] ?? p, idx)}
          disabled={
            autoRealizingId !== null || autoJianyingDraftExportingId !== null || activeCount === 0
          }
          title={activeCount === 0 ? '至少保留一段参与导出' : undefined}
          className="w-full inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded-xl border border-teal-500/45 bg-teal-500/10 text-[11px] text-teal-200 hover:bg-teal-500/18 disabled:opacity-60 transition-colors"
        >
          {autoJianyingDraftExportingId === p.plan_id ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              草稿导出中...
            </>
          ) : (
            <>仅导出剪映草稿</>
          )}
        </button>
        {autoRealizeMsg && <p className="text-[11px] text-emerald-300/80">{autoRealizeMsg}</p>}
        {autoRealizeDownloads[p.plan_id] && (
          <div className="space-y-1">
            <a
              href={autoRealizeDownloads[p.plan_id].url}
              download={autoRealizeDownloads[p.plan_id].filename}
              target="_blank"
              rel="noreferrer"
              className="block text-[11px] text-cyan-300 hover:text-cyan-200 underline underline-offset-2"
            >
              下载成片：{autoRealizeDownloads[p.plan_id].filename}
            </a>
          </div>
        )}
        {(() => {
          const jy = autoJianyingDraftDownloads[p.plan_id]
          if (!jy) return null
          if (jy.mode === 'direct') {
            return (
              <p className="text-[11px] text-teal-300/90 break-all leading-snug">
                剪映草稿目录：{jy.local_path}
              </p>
            )
          }
          return (
            <a
              href={jy.url}
              download={jy.filename}
              target="_blank"
              rel="noreferrer"
              className="block text-[11px] text-teal-300/90 hover:text-teal-200 underline underline-offset-2"
            >
              下载剪映草稿：{jy.filename}
            </a>
          )
        })()}
      </div>
    </div>
  )
}

