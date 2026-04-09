'use client'

import { Loader2 } from 'lucide-react'
import type { AutoEditPlanApi } from '@/lib/api'
import { HoverTruncatedTooltip } from '@/components/ui/hover-truncated-tooltip'
import type { ClipMetaByClip, SelectedPreviewState } from './autoEditTypes'
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
  onOpenDetailPlan: (plan: AutoEditPlanApi, index: number) => void
  onSelectPreview: (next: SelectedPreviewState) => void
  onRealizePlan: (plan: AutoEditPlanApi, index: number) => void
  autoRealizingId: string | null
  autoRealizeMsg: string
  autoRealizeDownloads: Record<string, { filename: string; url: string }>
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
  onOpenDetailPlan,
  onSelectPreview,
  onRealizePlan,
  autoRealizingId,
  autoRealizeMsg,
  autoRealizeDownloads,
}: AutoEditPlanCardProps) {
  const planTitle = p.title || `方案 ${idx + 1}`
  const eps = 0.05

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 space-y-2">
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
          <p>段落：{p.segments?.length ?? 0}</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onOpenDetailPlan(p, idx)}
          className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-200 hover:bg-slate-950/70"
          title="查看本方案的字幕、音频模式、片段选择等详情"
        >
          字幕详情 / 可编辑
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
          <span className="ml-1 text-slate-600">（共 {p.segments?.length ?? 0} 段）</span>
        </p>
        <div
          className={`mt-1 flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-950/40 px-2 py-2 ${
            expandedPreviewPlanIds.includes(p.plan_id)
              ? 'max-h-none'
              : 'max-h-24 overflow-y-auto'
          }`}
        >
          {(p.segments ?? []).map((s) => {
            const clipId = s.selected_clip_ids?.[0] || s.clip_group?.[0]?.clip_id
            const videoId = s.clip_group?.[0]?.video_id || null
            const cm = clipId ? clipMetaByClip[clipId] : undefined

            // 兼容“clip 内相对时间”语义：当窗口落在 clip 时长范围内，换算到源视频绝对时间后再展示/预览。
            const rawStart = Number(s.start_time_sec) || 0
            const rawEnd = Number(s.end_time_sec) || rawStart
            const clipDuration = cm ? Math.max(0, Number(cm.end_time) - Number(cm.start_time)) : null
            const windowDur = Math.max(0, rawEnd - rawStart)
            const canMapByClip =
              clipDuration != null &&
              clipDuration > 0 &&
              rawStart >= -eps &&
              rawEnd > rawStart &&
              windowDur <= clipDuration + eps
            let mappedStart = rawStart
            let mappedEnd = rawEnd
            if (canMapByClip && clipDuration != null) {
              if (rawEnd <= clipDuration + eps) {
                mappedStart = rawStart
              } else if (windowDur > 0) {
                // 越界时按“片段起点 + seg持续时间”展示/预览
                mappedStart = 0
              } else {
                mappedStart = Math.min(rawStart, Math.max(0, clipDuration - windowDur))
              }
              mappedStart = Math.max(0, Math.min(mappedStart, Math.max(0, clipDuration - windowDur)))
              mappedEnd = mappedStart + windowDur
            }
            const displayStart = canMapByClip && cm ? Number(cm.start_time) + mappedStart : rawStart
            const displayEnd = canMapByClip && cm ? Number(cm.start_time) + mappedEnd : rawEnd

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
                className="inline-flex items-center rounded-md border border-cyan-500/40 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] text-cyan-200 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-900/50 disabled:text-slate-500"
                title={
                  clipId
                    ? cm
                      ? canMapByClip
                        ? `已按片段起点换算（越界会钳制）：${fmt(rawStart)}–${fmt(rawEnd)} + clip起点${fmt(cm.start_time)} => ${fmt(displayStart)}–${fmt(displayEnd)}`
                        : `按方案时间窗预览：${fmt(displayStart)}–${fmt(displayEnd)}（clip区间 ${fmt(cm.start_time)}–${fmt(cm.end_time)}）`
                      : `加载库内时间中… 方案标注 ${fmt(rawStart)}–${fmt(rawEnd)}`
                    : '该片段缺少 clip_id，暂不可预览'
                }
              >
                #{s.order}（{fmt(displayStart)}-{fmt(displayEnd)}）
              </button>
            )
          })}
        </div>
        {(p.segments?.length ?? 0) > 12 && (
          <button
            type="button"
            onClick={() => togglePreviewExpand(p.plan_id)}
            className="mt-1 text-[11px] text-cyan-300 hover:text-cyan-200"
          >
            {expandedPreviewPlanIds.includes(p.plan_id) ? '折叠列表' : '展开列表'}
          </button>
        )}
      </div>

      <div className="pt-1 space-y-1">
        <button
          onClick={() => onRealizePlan(customPlanById[p.plan_id] ?? p, idx)}
          disabled={autoRealizingId !== null}
          className="w-full inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded-xl border border-emerald-500/50 bg-emerald-500/10 text-[11px] text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-60 transition-colors"
        >
          {autoRealizingId === p.plan_id ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              成片生成中...
            </>
          ) : (
            <>一键成片</>
          )}
        </button>
        {autoRealizeMsg && <p className="text-[11px] text-emerald-300/80">{autoRealizeMsg}</p>}
        {autoRealizeDownloads[p.plan_id] && (
          <a
            href={autoRealizeDownloads[p.plan_id].url}
            download={autoRealizeDownloads[p.plan_id].filename}
            target="_blank"
            rel="noreferrer"
            className="block text-[11px] text-cyan-300 hover:text-cyan-200 underline underline-offset-2"
          >
            下载成片：{autoRealizeDownloads[p.plan_id].filename}
          </a>
        )}
      </div>
    </div>
  )
}

