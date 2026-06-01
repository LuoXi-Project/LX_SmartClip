'use client'

import { useEffect, type Dispatch, type SetStateAction } from 'react'
import type { AutoEditPlanApi } from '@/lib/api'
import type { ClipMetaByClip, SelectedPreviewState } from './autoEditTypes'
import { AutoEditPlanWorkspace } from './AutoEditPlanWorkspace'

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

/** 全屏弹窗版剪辑台（主流程已改为页内 inline；保留供需要大屏时使用） */
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
  useEffect(() => {
    if (!detailPlan) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [detailPlan, onClose])

  if (!detailPlan) return null

  const planTitle = detailPlan.plan.title || `方案 ${detailPlan.index + 1}`

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label="方案剪辑台"
    >
      <button type="button" className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} aria-label="关闭" />
      <div className="relative flex flex-col w-full max-w-[min(96vw,1280px)] max-h-[min(92vh,900px)] rounded-2xl border border-slate-800 bg-[#0d0f14] shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-3 flex-shrink-0">
          <p className="text-sm font-semibold text-slate-100 truncate">{planTitle} · 全屏剪辑台</p>
          <button
            type="button"
            onClick={onClose}
            className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70 flex-shrink-0"
          >
            关闭 Esc
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3 min-h-0">
          <AutoEditPlanWorkspace
            activePlan={detailPlan}
            detailEditMode={detailEditMode}
            setDetailEditMode={setDetailEditMode}
            detailDraft={detailDraft}
            setDetailDraft={setDetailDraft}
            setCustomPlanById={setCustomPlanById}
            clipMetaByClip={clipMetaByClip}
            setSelectedPreview={setSelectedPreview}
          />
        </div>
      </div>
    </div>
  )
}
