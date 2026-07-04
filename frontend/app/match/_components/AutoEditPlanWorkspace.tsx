'use client'

import { ChevronDown, ChevronUp } from 'lucide-react'
import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import type { AutoEditPlanApi } from '@/lib/api'
import type { ClipMetaByClip, SelectedPreviewState } from './autoEditTypes'
import { PlanEditWorkspace } from './PlanEditWorkspace'
import { fmt } from './types'

type ViewMode = 'timeline' | 'detail' | 'copy'

export type AutoEditPlanWorkspaceProps = {
  activePlan: { plan: AutoEditPlanApi; index: number }
  onDeselect?: () => void
  detailEditMode: boolean
  setDetailEditMode: Dispatch<SetStateAction<boolean>>
  detailDraft: AutoEditPlanApi | null
  setDetailDraft: Dispatch<SetStateAction<AutoEditPlanApi | null>>
  setCustomPlanById: Dispatch<SetStateAction<Record<string, AutoEditPlanApi>>>
  clipMetaByClip: ClipMetaByClip
  setSelectedPreview: Dispatch<SetStateAction<SelectedPreviewState | null>>
  className?: string
}

export function AutoEditPlanWorkspace({
  activePlan,
  onDeselect,
  detailEditMode,
  setDetailEditMode,
  detailDraft,
  setDetailDraft,
  setCustomPlanById,
  clipMetaByClip,
  setSelectedPreview,
  className = '',
}: AutoEditPlanWorkspaceProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('timeline')
  const [copyStatus, setCopyStatus] = useState<'idle' | 'ok' | 'fail'>('idle')
  const [bodyExpanded, setBodyExpanded] = useState(true)

  const workingPlan = detailDraft ?? activePlan.plan
  const segments = workingPlan.segments ?? []
  const activeSegments = useMemo(() => segments.filter((s) => !s.exclude_from_output), [segments])
  const mergedCopyText = useMemo(() => {
    return activeSegments
      .map((s) => s.subtitle?.text?.trim())
      .filter((txt): txt is string => Boolean(txt))
      .join('\n')
  }, [activeSegments])

  const planTitle = activePlan.plan.title || `方案 ${activePlan.index + 1}`

  useEffect(() => {
    setViewMode('timeline')
    setCopyStatus('idle')
    setBodyExpanded(true)
  }, [activePlan.plan.plan_id])

  useEffect(() => {
    if (copyStatus === 'idle') return
    const timer = window.setTimeout(() => setCopyStatus('idle'), 1500)
    return () => window.clearTimeout(timer)
  }, [copyStatus])

  return (
    <section
      className={`rounded-2xl border border-cyan-500/25 bg-gradient-to-b from-cyan-950/20 to-slate-950/40 p-4 space-y-3 ${className}`}
      aria-label="方案剪辑时间轴工作区"
      id={`plan-workspace-${activePlan.plan.plan_id}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-cyan-200 uppercase tracking-widest">
            {planTitle} · 剪辑时间轴
          </p>
          <p className="text-[11px] text-slate-500 mt-0.5">
            {activeSegments.length}/{segments.length} 段参与成片 ·{' '}
            {activePlan.plan.mode === 'auto'
              ? '自动'
              : activePlan.plan.mode === 'voiceover'
                ? '配音'
                : '原声'}
            {detailEditMode && <span className="ml-2 text-cyan-400/90">编辑中</span>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 flex-shrink-0">
          {onDeselect ? (
            <button
              type="button"
              onClick={onDeselect}
              className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70"
            >
              收起工作区
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setBodyExpanded((v) => !v)}
            className="inline-flex items-center gap-1 text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70"
          >
            {bodyExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            {bodyExpanded ? '折叠详情' : '展开详情'}
          </button>
        </div>
      </div>

      {bodyExpanded && (
      <>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800/80 bg-slate-950/40 px-3 py-2">
        <div className="inline-flex items-center rounded-lg border border-slate-700 bg-slate-950/40 p-0.5">
          {(
            [
              ['timeline', '时间轴剪辑'],
              ['detail', '段落列表'],
              ['copy', '文案速览'],
            ] as const
          ).map(([mode, label]) => (
            <button
              key={mode}
              type="button"
              onClick={() => setViewMode(mode)}
              className={`text-[11px] rounded-md px-2.5 py-1 transition-colors ${
                viewMode === mode ? 'bg-cyan-500/20 text-cyan-200' : 'text-slate-300 hover:bg-slate-900/70'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => setDetailEditMode((v) => !v)}
            className={`text-[11px] rounded-lg border px-2 py-1 transition-colors ${
              detailEditMode
                ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-200'
                : 'border-slate-700 bg-slate-950/40 text-slate-300 hover:bg-slate-950/70'
            }`}
          >
            {detailEditMode ? '退出编辑' : '进入编辑'}
          </button>
          <button
            type="button"
            disabled={!detailDraft}
            onClick={() => {
              if (!detailDraft) return
              setCustomPlanById((prev) => ({ ...prev, [detailDraft.plan_id]: detailDraft }))
              setDetailEditMode(false)
            }}
            className="text-[11px] rounded-lg border border-emerald-500/60 bg-emerald-500/15 px-2 py-1 text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
          >
            保存修改
          </button>
          <button
            type="button"
            disabled={!detailDraft}
            onClick={() => {
              if (!detailDraft) return
              setCustomPlanById((prev) => {
                const next = { ...prev }
                delete next[detailDraft.plan_id]
                return next
              })
              setDetailDraft(activePlan.plan)
              setDetailEditMode(false)
            }}
            className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70 disabled:opacity-50"
          >
            恢复默认
          </button>
        </div>
      </div>

      <div className="min-h-0">
        {viewMode === 'timeline' ? (
          <PlanEditWorkspace
            plan={workingPlan}
            setPlan={setDetailDraft}
            clipMetaByClip={clipMetaByClip}
            editable={detailEditMode}
            planTitle={planTitle}
            onExternalPreview={setSelectedPreview}
          />
        ) : viewMode === 'copy' ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] text-slate-400">文案速览（仅字幕文本）</p>
              <button
                type="button"
                onClick={async () => {
                  if (!mergedCopyText.trim()) return
                  try {
                    await navigator.clipboard.writeText(mergedCopyText)
                    setCopyStatus('ok')
                  } catch {
                    setCopyStatus('fail')
                  }
                }}
                disabled={!mergedCopyText.trim()}
                className="text-[11px] rounded-lg border border-cyan-500/50 bg-cyan-500/10 px-2 py-1 text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
              >
                {copyStatus === 'ok' ? '复制成功' : copyStatus === 'fail' ? '复制失败' : '复制全文案'}
              </button>
            </div>
            <textarea
              value={mergedCopyText}
              readOnly
              rows={12}
              className="mt-2 w-full rounded-lg bg-slate-950/60 border border-slate-700 px-3 py-2 text-xs leading-5 text-slate-100 outline-none"
              placeholder="当前方案没有可用字幕文案。"
            />
          </div>
        ) : (
          <PlanDetailSegmentList
            segments={segments}
            detailEditMode={detailEditMode}
            setDetailDraft={setDetailDraft}
            activePlan={activePlan}
            clipMetaByClip={clipMetaByClip}
            setSelectedPreview={setSelectedPreview}
            planTitle={planTitle}
          />
        )}
      </div>
      </>
      )}
    </section>
  )
}

function PlanDetailSegmentList({
  segments,
  detailEditMode,
  setDetailDraft,
  activePlan,
  clipMetaByClip,
  setSelectedPreview,
  planTitle,
}: {
  segments: AutoEditPlanApi['segments']
  detailEditMode: boolean
  setDetailDraft: Dispatch<SetStateAction<AutoEditPlanApi | null>>
  activePlan: { plan: AutoEditPlanApi; index: number }
  clipMetaByClip: ClipMetaByClip
  setSelectedPreview: Dispatch<SetStateAction<SelectedPreviewState | null>>
  planTitle: string
}) {
  const activeCount = segments.filter((s) => !s.exclude_from_output).length

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2 space-y-2">
      <p className="text-[11px] text-slate-400">
        段落列表 · {activeCount}/{segments.length} 段参与成片
      </p>
      <div className="space-y-2 max-h-[50vh] overflow-y-auto styled-scrollbar">
        {segments.map((s, segIdx) => {
          const excluded = !!s.exclude_from_output
          const clipId = s.selected_clip_ids?.[0] || s.clip_group?.[0]?.clip_id || ''
          const cm = clipId ? clipMetaByClip[clipId] : undefined
          const abs0 = s.start_time_sec
          const abs1 = s.end_time_sec
          const subtitleText = s.subtitle?.text?.trim() || ''

          return (
            <div
              key={s.id}
              className={`rounded-xl border px-3 py-2 ${
                excluded ? 'border-amber-900/60 bg-amber-950/20' : 'border-slate-800 bg-slate-950/30'
              }`}
            >
              <p className={`text-xs font-semibold ${excluded ? 'text-amber-200/90' : 'text-slate-200'}`}>
                #{s.order} · {fmt(abs0)}–{fmt(abs1)}
                {excluded && <span className="ml-2 text-[10px] text-amber-400/90">已弃用</span>}
              </p>
              {detailEditMode && (
                <label className="mt-2 flex cursor-pointer items-center gap-2 text-[11px] text-slate-300">
                  <input
                    type="checkbox"
                    checked={excluded}
                    onChange={() => {
                      setDetailDraft((prev) => {
                        if (!prev) return prev
                        const segs = [...(prev.segments ?? [])]
                        segs[segIdx] = { ...segs[segIdx], exclude_from_output: !excluded }
                        return { ...prev, segments: segs }
                      })
                    }}
                    className="rounded border-slate-600"
                  />
                  弃用本段
                </label>
              )}
              <p className="text-xs text-slate-300 mt-1 whitespace-pre-wrap">{subtitleText || '（无字幕）'}</p>
              {clipId && (
                <button
                  type="button"
                  className="mt-2 text-[11px] rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 text-cyan-200"
                  onClick={() =>
                    setSelectedPreview({
                      planId: activePlan.plan.plan_id,
                      planTitle,
                      segmentId: s.id,
                      order: s.order,
                      clipId,
                      videoId: cm?.video_id ?? null,
                      source: cm?.video_id ? 'video' : 'clip',
                      startSec: abs0,
                      endSec: abs1,
                    })
                  }
                >
                  片段预览
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
