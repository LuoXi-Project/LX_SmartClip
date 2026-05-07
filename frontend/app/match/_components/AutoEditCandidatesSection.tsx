'use client'

import { useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { AutoEditPlanApi } from '@/lib/api'
import type { ClipMetaByClip, SelectedPreviewState } from './autoEditTypes'
import { AutoEditPreviewPanel } from './AutoEditPreviewPanel'
import { AutoEditPlanCard } from './AutoEditPlanCard'

export type AutoEditCandidatesSectionProps = {
  autoPlans: AutoEditPlanApi[]

  subtitleEnabled: boolean
  autoExpandedPlanIds: string[]
  onTogglePlanExpand: (planId: string) => void

  clipMetaByClip: ClipMetaByClip

  selectedPreview: SelectedPreviewState | null
  setSelectedPreview: Dispatch<SetStateAction<SelectedPreviewState | null>>

  customPlanById: Record<string, AutoEditPlanApi>

  onOpenDetailPlan: (plan: AutoEditPlanApi, index: number) => void
  onRealizePlan: (plan: AutoEditPlanApi, index: number) => void

  autoRealizingId: string | null
  autoRealizeMsg: string
  autoRealizeDownloads: Record<
    string,
    { filename: string; url: string; jianyingDraftFilename?: string; jianyingDraftUrl?: string }
  >
  alsoExportJianyingDraft?: boolean
  onAlsoExportJianyingDraftChange?: (value: boolean) => void
}

export function AutoEditCandidatesSection({
  autoPlans,
  subtitleEnabled,
  autoExpandedPlanIds,
  onTogglePlanExpand,
  clipMetaByClip,
  selectedPreview,
  setSelectedPreview,
  customPlanById,
  onOpenDetailPlan,
  onRealizePlan,
  autoRealizingId,
  autoRealizeMsg,
  autoRealizeDownloads,
  alsoExportJianyingDraft = false,
  onAlsoExportJianyingDraftChange,
}: AutoEditCandidatesSectionProps) {
  const [expandedPreviewPlanIds, setExpandedPreviewPlanIds] = useState<string[]>([])

  const togglePreviewExpand = (planId: string) => {
    setExpandedPreviewPlanIds((prev) =>
      prev.includes(planId) ? prev.filter((id) => id !== planId) : [...prev, planId]
    )
  }

  return (
    <section className="space-y-3">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
        候选方案 · {autoPlans.length} 个
      </p>

      <AutoEditPreviewPanel
        selectedPreview={selectedPreview}
        setSelectedPreview={setSelectedPreview}
        clipMetaByClip={clipMetaByClip}
      />

      {onAlsoExportJianyingDraftChange ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-medium text-slate-200">一键成片时同时导出剪映草稿</p>
            <p className="text-[10px] text-slate-500 mt-0.5">
              与成片同一时间轴；解压草稿文件夹到剪映草稿目录即可继续剪辑
            </p>
          </div>
          <button
            type="button"
            onClick={() => onAlsoExportJianyingDraftChange(!alsoExportJianyingDraft)}
            className={`relative w-9 h-5 rounded-full shrink-0 transition-colors ${
              alsoExportJianyingDraft ? 'bg-emerald-600' : 'bg-slate-700'
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                alsoExportJianyingDraft ? 'translate-x-4' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
      ) : null}

      <div className="grid md:grid-cols-2 gap-3">
        {autoPlans.map((p, idx) => (
          <AutoEditPlanCard
            key={p.plan_id || idx}
            p={p}
            idx={idx}
            subtitleEnabled={subtitleEnabled}
            customPlanById={customPlanById}
            autoExpandedPlanIds={autoExpandedPlanIds}
            onTogglePlanExpand={onTogglePlanExpand}
            expandedPreviewPlanIds={expandedPreviewPlanIds}
            togglePreviewExpand={togglePreviewExpand}
            clipMetaByClip={clipMetaByClip}
            onOpenDetailPlan={(plan, index) => onOpenDetailPlan(plan, index)}
            onSelectPreview={setSelectedPreview}
            onRealizePlan={onRealizePlan}
            autoRealizingId={autoRealizingId}
            autoRealizeMsg={autoRealizeMsg}
            autoRealizeDownloads={autoRealizeDownloads}
          />
        ))}
      </div>
    </section>
  )
}

