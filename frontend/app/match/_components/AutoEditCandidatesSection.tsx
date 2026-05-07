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
  onExportJianyingDraft: (plan: AutoEditPlanApi, index: number) => void

  autoRealizingId: string | null
  autoJianyingDraftExportingId: string | null
  autoRealizeMsg: string
  autoRealizeDownloads: Record<string, { filename: string; url: string }>
  autoJianyingDraftDownloads: Record<string, { filename: string; url: string }>
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
  onExportJianyingDraft,
  autoRealizingId,
  autoJianyingDraftExportingId,
  autoRealizeMsg,
  autoRealizeDownloads,
  autoJianyingDraftDownloads,
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
            onExportJianyingDraft={onExportJianyingDraft}
            autoRealizingId={autoRealizingId}
            autoJianyingDraftExportingId={autoJianyingDraftExportingId}
            autoRealizeMsg={autoRealizeMsg}
            autoRealizeDownloads={autoRealizeDownloads}
            autoJianyingDraftDownloads={autoJianyingDraftDownloads}
          />
        ))}
      </div>
    </section>
  )
}
