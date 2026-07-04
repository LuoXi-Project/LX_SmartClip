'use client'

import { useMemo, useCallback, type Dispatch, type SetStateAction } from 'react'
import { Layers } from 'lucide-react'
import type { AutoEditPlanApi } from '@/lib/api'
import { useAutoEditBgmTracks, useAutoEditClipMetaByPlans } from '@/app/match/_components/autoEditPanelHooks'
import { patchAgentWorkspace } from '@/lib/agent-api'
import { useStudioStore } from '@/lib/studio-store'
import { PlanEditWorkspace } from '@/app/match/_components/PlanEditWorkspace'
import { StudioPlanActions } from './StudioPlanActions'
import { StudioExportGuide } from './StudioExportGuide'
import { ExportResultPanel } from './ExportResultPanel'
import { isVideoExport, payloadToExportArtifact } from '@/lib/studio-media-url'
import { useStudioMediaConfig } from './useStudioMediaConfig'
import { bgmTrackLabel } from '@/lib/studio-media-config'
import type { ArtifactRef } from '@/lib/agent-types'
import { StudioPanelHeaderAction } from './StudioPanelHeaderAction'

function latestVideoExport(exports: Record<string, unknown>[] | undefined) {
  if (!exports?.length) return null
  for (let i = exports.length - 1; i >= 0; i -= 1) {
    const item = exports[i]
    if (item && isVideoExport(item)) return item
  }
  return null
}

export function ArtifactCanvas() {
  const {
    sessionId,
    workspace,
    selectedArtifact,
    setWorkspace,
    setSelectedArtifact,
    setInspectorTab,
  } = useStudioStore()
  const { media } = useStudioMediaConfig()
  const { bgmTracks } = useAutoEditBgmTracks()

  const exportArtifact: ArtifactRef | null = useMemo(() => {
    if (selectedArtifact?.type === 'export') return selectedArtifact
    const last = latestVideoExport(workspace?.last_exports)
    if (last) return payloadToExportArtifact(last)
    return null
  }, [selectedArtifact, workspace?.last_exports])

  const plan: AutoEditPlanApi | null = useMemo(() => {
    if (selectedArtifact?.type === 'plan') {
      return selectedArtifact.payload as unknown as AutoEditPlanApi
    }
    if (!workspace?.plans?.length) return null
    const pid = workspace.active_plan_id
    if (pid) return workspace.plans.find((p) => p.plan_id === pid) ?? workspace.plans[0]
    return workspace.plans[0]
  }, [workspace, selectedArtifact])

  const plansForMeta = useMemo(() => (plan ? [plan] : []), [plan])
  const clipMetaByClip = useAutoEditClipMetaByPlans(plansForMeta)

  const bgmLabel = useMemo(
    () =>
      media.bgm.enabled
        ? media.bgm.mode === 'manual' && media.bgm.track_ids.length
          ? bgmTrackLabel(media.bgm.track_ids, bgmTracks)
          : '自动选曲'
        : '',
    [media.bgm, bgmTracks]
  )

  const setPlan: Dispatch<SetStateAction<AutoEditPlanApi | null>> = useCallback(
    (updater) => {
      if (!sessionId || !workspace || !plan) return
      const next = typeof updater === 'function' ? updater(plan) : updater
      if (!next) return
      void (async () => {
        const plans = workspace.plans.map((p) =>
          p.plan_id === next.plan_id ? next : p
        )
        const res = await patchAgentWorkspace(sessionId, {
          plans,
          active_plan_id: next.plan_id,
        })
        setWorkspace(res.workspace)
        setSelectedArtifact({
          type: 'plan',
          id: next.plan_id,
          payload: next as unknown as Record<string, unknown>,
        })
      })()
    },
    [sessionId, workspace, plan, setWorkspace, setSelectedArtifact]
  )

  return (
    <div className="flex flex-col h-full bg-[#0a0c10] min-w-0">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        <Layers className="w-4 h-4 text-indigo-400" />
        <span className="text-sm font-medium text-slate-200">产物画布</span>
        {workspace && (
          <span className="text-[10px] text-slate-500">
            阶段 · {workspace.pipeline_phase}
          </span>
        )}
        <StudioPanelHeaderAction panelId="canvas" />
      </div>
      <div className="flex-1 overflow-auto styled-scrollbar min-h-0 p-4 space-y-4">
        {exportArtifact ? <ExportResultPanel artifact={exportArtifact} /> : null}

        {plan ? (
          <>
            <StudioExportGuide plan={plan} />
            <StudioPlanActions plan={plan} />
            <PlanEditWorkspace
              plan={plan}
              setPlan={setPlan}
              clipMetaByClip={clipMetaByClip}
              editable
              planTitle={plan.title || '方案'}
              subtitleStyle={media.subtitle.style}
              subtitleEnabled={media.subtitle.enabled}
              bgmTimeline={
                media.bgm.enabled
                  ? { enabled: true, label: bgmLabel || 'BGM' }
                  : undefined
              }
              onBgmTrackFocus={() => setInspectorTab('bgm')}
            />
          </>
        ) : !exportArtifact ? (
          <StudioExportGuide variant="overview" />
        ) : null}
      </div>
    </div>
  )
}
