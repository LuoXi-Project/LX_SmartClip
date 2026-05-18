'use client'

import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import type { AutoEditPlanApi } from '@/lib/api'
import type { ClipMetaByClip, SelectedPreviewState } from './autoEditTypes'
import { PlanEditWorkspace } from './PlanEditWorkspace'
import { fmt } from './types'

export type AutoEditDetailModalProps = {
  detailPlan: { plan: AutoEditPlanApi; index: number } | null
  onClose: () => void

  detailEditMode: boolean
  setDetailEditMode: Dispatch<SetStateAction<boolean>>

  detailDraft: AutoEditPlanApi | null
  setDetailDraft: Dispatch<SetStateAction<AutoEditPlanApi | null>>

  setCustomPlanById: Dispatch<SetStateAction<Record<string, AutoEditPlanApi>>>

  clipMetaByClip: ClipMetaByClip
  setSelectedPreview: Dispatch<SetStateAction<SelectedPreviewState | null>>
}

type ViewMode = 'timeline' | 'detail' | 'copy'

export function AutoEditDetailModal({
  detailPlan,
  onClose,
  detailEditMode,
  setDetailEditMode,
  detailDraft,
  setDetailDraft,
  setCustomPlanById,
  clipMetaByClip,
  setSelectedPreview,
}: AutoEditDetailModalProps) {
  if (!detailPlan) return null

  const [viewMode, setViewMode] = useState<ViewMode>('timeline')
  const [copyStatus, setCopyStatus] = useState<'idle' | 'ok' | 'fail'>('idle')

  const workingPlan = detailDraft ?? detailPlan.plan
  const segments = workingPlan.segments ?? []
  const activeSegments = useMemo(() => segments.filter((s) => !s.exclude_from_output), [segments])
  const mergedCopyText = useMemo(() => {
    return activeSegments
      .map((s) => s.subtitle?.text?.trim())
      .filter((txt): txt is string => Boolean(txt))
      .join('\n')
  }, [activeSegments])

  const planTitle = detailPlan.plan.title || `方案 ${detailPlan.index + 1}`

  useEffect(() => {
    setViewMode('timeline')
    setCopyStatus('idle')
  }, [detailPlan.plan.plan_id])

  useEffect(() => {
    if (copyStatus === 'idle') return
    const timer = window.setTimeout(() => setCopyStatus('idle'), 1500)
    return () => window.clearTimeout(timer)
  }, [copyStatus])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label="方案剪辑台"
    >
      <button type="button" className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} aria-label="关闭" />
      <div className="relative flex flex-col w-full max-w-[min(96vw,1280px)] max-h-[min(92vh,900px)] rounded-2xl border border-slate-800 bg-[#0d0f14] shadow-2xl overflow-hidden">
        <div className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-3 flex-shrink-0">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-100 truncate">
              {planTitle} · 剪辑工作区
            </p>
            <p className="text-[11px] text-slate-500 mt-0.5">
              {activeSegments.length}/{segments.length} 段参与成片 ·{' '}
              {detailPlan.plan.mode === 'auto'
                ? '自动'
                : detailPlan.plan.mode === 'voiceover'
                  ? '配音'
                  : '原声'}
              {detailEditMode && <span className="ml-2 text-cyan-400/90">编辑中</span>}
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

        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 border-b border-slate-800/80 bg-slate-950/40 flex-shrink-0">
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
                setDetailDraft(detailPlan.plan)
                setDetailEditMode(false)
              }}
              className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70 disabled:opacity-50"
            >
              恢复默认
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 min-h-0">
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
                rows={16}
                className="mt-2 w-full rounded-lg bg-slate-950/60 border border-slate-700 px-3 py-2 text-xs leading-5 text-slate-100 outline-none"
                placeholder="当前方案没有可用字幕文案。"
              />
            </div>
          ) : (
            <DetailSegmentList
              segments={segments}
              detailEditMode={detailEditMode}
              setDetailDraft={setDetailDraft}
              detailPlan={detailPlan}
              clipMetaByClip={clipMetaByClip}
              setSelectedPreview={setSelectedPreview}
              planTitle={planTitle}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function DetailSegmentList({
  segments,
  detailEditMode,
  setDetailDraft,
  detailPlan,
  clipMetaByClip,
  setSelectedPreview,
  planTitle,
}: {
  segments: AutoEditPlanApi['segments']
  detailEditMode: boolean
  setDetailDraft: Dispatch<SetStateAction<AutoEditPlanApi | null>>
  detailPlan: { plan: AutoEditPlanApi; index: number }
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
      <div className="space-y-2 max-h-[60vh] overflow-y-auto">
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
                      planId: detailPlan.plan.plan_id,
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
