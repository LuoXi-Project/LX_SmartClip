'use client'

import { useEffect, useState } from 'react'
import {
  type AutoEditMode,
  type AutoEditPlanApi,
  type AutoJianyingDraftDownloadEntryApi,
} from '@/lib/api'
import { useAutoEditBgmTracks, useAutoEditClipMetaByPlans } from './autoEditPanelHooks'
import type { AutoPlanStage, SelectedPreviewState } from './autoEditTypes'
import { AutoEditPlanWorkspace } from './AutoEditPlanWorkspace'
import { AutoEditDetailModal } from './AutoEditDetailModal'
import { AutoEditPlannerSection } from './AutoEditPlannerSection'
import { AutoEditCandidatesSection } from './AutoEditCandidatesSection'

export type AutoEditPanelProps = {
  autoPrompt: string
  onAutoPromptChange: (value: string) => void
  autoMode: AutoEditMode
  onAutoModeChange: (value: AutoEditMode) => void
  autoTargetDuration: number | ''
  onAutoTargetDurationChange: (value: number | '') => void
  autoNumPlans: number
  onAutoNumPlansChange: (value: number) => void
  autoBgmMixEnabled: boolean
  onAutoBgmMixEnabledChange: (value: boolean) => void
  autoBgmPlanPolicy: 'auto' | 'none' | 'user' | 'ai'
  onAutoBgmPlanPolicyChange: (value: 'auto' | 'none' | 'user' | 'ai') => void
  autoBgmTrackFilename: string
  onAutoBgmTrackFilenameChange: (value: string) => void
  showAutoCustomBgmConfig?: boolean
  autoCustomBgmEnabled?: boolean
  onAutoCustomBgmEnabledChange?: (value: boolean) => void
  autoCustomBgmTrackIds?: string[]
  onToggleAutoCustomBgmTrack?: (trackId: string) => void
  autoCustomBgmVolumeByTrackId?: Record<string, number>
  onAutoCustomBgmTrackVolumeChange?: (trackId: string, volumeDb: number) => void
  autoCustomBgmTimelineSegments?: Array<{ id: string; startSec: number; endSec: number; trackId?: string; volumeDb?: number }>
  onAddAutoCustomBgmTimelineSegment?: () => void
  onRemoveAutoCustomBgmTimelineSegment?: (id: string) => void
  onUpdateAutoCustomBgmTimelineSegment?: (
    id: string,
    patch: Partial<{ startSec: number; endSec: number; trackId?: string; volumeDb?: number }>
  ) => void
  showVoiceoverBgmConfig?: boolean
  voiceoverBgmEnabled?: boolean
  onVoiceoverBgmEnabledChange?: (value: boolean) => void
  bgmTracksForVoiceover?: import('@/lib/api').BgmTrack[]
  bgmListErrorForVoiceover?: string
  selectedVoiceoverBgmTrackIds?: string[]
  onToggleVoiceoverBgmTrack?: (trackId: string) => void
  voiceoverBgmVolumeByTrackId?: Record<string, number>
  onVoiceoverBgmTrackVolumeChange?: (trackId: string, volumeDb: number) => void
  voiceoverBgmTimelineSegments?: Array<{ id: string; startSec: number; endSec: number; trackId?: string; volumeDb?: number }>
  onAddVoiceoverBgmTimelineSegment?: () => void
  onRemoveVoiceoverBgmTimelineSegment?: (id: string) => void
  onUpdateVoiceoverBgmTimelineSegment?: (
    id: string,
    patch: Partial<{ startSec: number; endSec: number; trackId?: string; volumeDb?: number }>
  ) => void
  autoUseTimelineEngine: boolean
  onAutoUseTimelineEngineChange: (value: boolean) => void
  processingProfileLocked?: boolean
  processingProfileHint?: string
  autoContentStyle: 'generic' | 'ecommerce' | 'voiceover' | 'commentary'
  onAutoContentStyleChange: (value: 'generic' | 'ecommerce' | 'voiceover' | 'commentary') => void
  autoEventsAdvancedEnabled: boolean
  onAutoEventsAdvancedEnabledChange: (value: boolean) => void
  autoEventsMaxClipsPerBatch: number | ''
  onAutoEventsMaxClipsPerBatchChange: (value: number | '') => void
  autoEventsMaxCharsPerBatch: number | ''
  onAutoEventsMaxCharsPerBatchChange: (value: number | '') => void
  autoEventsBatchOverlapClips: number | ''
  onAutoEventsBatchOverlapClipsChange: (value: number | '') => void
  autoEventsMaxBatches: number | ''
  onAutoEventsMaxBatchesChange: (value: number | '') => void
  recommendedProfile: { clips: number; chars: number; overlap: number; batches: number }
  estimatedBatches: number
  estimatedSeconds: number
  estimatedTotalClips: number
  onResetAdvancedToRecommended: () => void
  autoExplain: boolean
  onAutoExplainChange: (value: boolean) => void
  autoLoading: boolean
  autoError: string
  autoPlans: AutoEditPlanApi[]
  autoExpandedPlanIds: string[]
  onTogglePlanExpand: (planId: string) => void
  autoRealizingId: string | null
  autoRealizeMsg: string
  autoRealizeDownloads: Record<string, { filename: string; url: string }>
  autoPlanLogs: string[]
  autoPlanElapsedSec: number
  autoPlanStage: AutoPlanStage
  autoPlanStagePercent: Record<AutoPlanStage, number>
  subtitleEnabled: boolean
  onGeneratePlans: () => void
  onRealizePlan: (plan: AutoEditPlanApi, index: number) => void
  /** 仅导出剪映草稿 ZIP（与成片互斥） */
  autoJianyingDraftExportingId: string | null
  autoJianyingDraftDownloads: Record<string, AutoJianyingDraftDownloadEntryApi>
  onExportJianyingDraft: (plan: AutoEditPlanApi, index: number) => void
  /** 口播快剪：隐藏 LLM 规划区，仅保留 BGM 与方案卡片（方案由上方快剪面板生成） */
  hideLlmPlannerUi?: boolean
  plannerVariant?: 'default' | 'film'
  candidatesSectionTitle?: string
}

export function AutoEditPanel({
  autoPrompt,
  onAutoPromptChange,
  autoMode,
  onAutoModeChange,
  autoTargetDuration,
  onAutoTargetDurationChange,
  autoNumPlans,
  onAutoNumPlansChange,
  autoBgmMixEnabled,
  onAutoBgmMixEnabledChange,
  autoBgmPlanPolicy,
  onAutoBgmPlanPolicyChange,
  autoBgmTrackFilename,
  onAutoBgmTrackFilenameChange,
  showAutoCustomBgmConfig = false,
  autoCustomBgmEnabled = false,
  onAutoCustomBgmEnabledChange,
  autoCustomBgmTrackIds = [],
  onToggleAutoCustomBgmTrack,
  autoCustomBgmVolumeByTrackId = {},
  onAutoCustomBgmTrackVolumeChange,
  autoCustomBgmTimelineSegments = [],
  onAddAutoCustomBgmTimelineSegment,
  onRemoveAutoCustomBgmTimelineSegment,
  onUpdateAutoCustomBgmTimelineSegment,
  showVoiceoverBgmConfig = false,
  voiceoverBgmEnabled = false,
  onVoiceoverBgmEnabledChange,
  bgmTracksForVoiceover,
  bgmListErrorForVoiceover = '',
  selectedVoiceoverBgmTrackIds = [],
  onToggleVoiceoverBgmTrack,
  voiceoverBgmVolumeByTrackId = {},
  onVoiceoverBgmTrackVolumeChange,
  voiceoverBgmTimelineSegments = [],
  onAddVoiceoverBgmTimelineSegment,
  onRemoveVoiceoverBgmTimelineSegment,
  onUpdateVoiceoverBgmTimelineSegment,
  autoUseTimelineEngine,
  onAutoUseTimelineEngineChange,
  processingProfileLocked = false,
  processingProfileHint,
  autoContentStyle,
  onAutoContentStyleChange,
  autoEventsAdvancedEnabled,
  onAutoEventsAdvancedEnabledChange,
  autoEventsMaxClipsPerBatch,
  onAutoEventsMaxClipsPerBatchChange,
  autoEventsMaxCharsPerBatch,
  onAutoEventsMaxCharsPerBatchChange,
  autoEventsBatchOverlapClips,
  onAutoEventsBatchOverlapClipsChange,
  autoEventsMaxBatches,
  onAutoEventsMaxBatchesChange,
  recommendedProfile,
  estimatedBatches,
  estimatedSeconds,
  estimatedTotalClips,
  onResetAdvancedToRecommended,
  autoExplain,
  onAutoExplainChange,
  autoLoading,
  autoError,
  autoPlans,
  autoExpandedPlanIds,
  onTogglePlanExpand,
  autoRealizingId,
  autoRealizeMsg,
  autoRealizeDownloads,
  autoPlanLogs,
  autoPlanElapsedSec,
  autoPlanStage,
  autoPlanStagePercent,
  subtitleEnabled,
  onGeneratePlans,
  onRealizePlan,
  autoJianyingDraftExportingId,
  autoJianyingDraftDownloads,
  onExportJianyingDraft,
  hideLlmPlannerUi = false,
  plannerVariant = 'default',
  candidatesSectionTitle,
}: AutoEditPanelProps) {
  const [activePlan, setActivePlan] = useState<{
    plan: AutoEditPlanApi
    index: number
  } | null>(null)
  const [fullscreenPlan, setFullscreenPlan] = useState<{
    plan: AutoEditPlanApi
    index: number
  } | null>(null)
  /** 用户对候选方案的本地可编辑覆盖（不会影响重新生成的 plans） */
  const [customPlanById, setCustomPlanById] = useState<Record<string, AutoEditPlanApi>>({})
  const [detailEditMode, setDetailEditMode] = useState(false)
  const [detailDraft, setDetailDraft] = useState<AutoEditPlanApi | null>(null)
  const [selectedPreview, setSelectedPreview] = useState<SelectedPreviewState | null>(null)
  /** clip 元数据用于预览与详情展示；成片裁剪由后端按方案时间窗处理 */
  const clipMetaByClip = useAutoEditClipMetaByPlans(autoPlans)
  const { bgmTracks, bgmListError } = useAutoEditBgmTracks()

  useEffect(() => {
    if (autoPlans.length === 0) {
      setActivePlan(null)
      return
    }
    setActivePlan((prev) => {
      if (prev && autoPlans.some((p) => p.plan_id === prev.plan.plan_id)) {
        const idx = autoPlans.findIndex((p) => p.plan_id === prev.plan.plan_id)
        return idx >= 0 ? { plan: autoPlans[idx], index: idx } : { plan: autoPlans[0], index: 0 }
      }
      return { plan: autoPlans[0], index: 0 }
    })
  }, [autoPlans])

  useEffect(() => {
    if (!activePlan) return
    const pid = activePlan.plan.plan_id
    const base = customPlanById[pid] ?? activePlan.plan
    setDetailDraft(base)
    setDetailEditMode(true)
  }, [customPlanById, activePlan])

  const selectPlan = (plan: AutoEditPlanApi, index: number) => {
    setActivePlan({ plan, index })
  }

  return (
    <>
      <AutoEditPlannerSection
        hideLlmPlannerUi={hideLlmPlannerUi}
        plannerVariant={plannerVariant}
        bgmTracks={bgmTracks}
        bgmListError={bgmListError}
        autoError={autoError}
        autoLoading={autoLoading}
        autoPlansCount={autoPlans.length}
        autoPrompt={autoPrompt}
        onAutoPromptChange={onAutoPromptChange}
        autoMode={autoMode}
        onAutoModeChange={onAutoModeChange}
        autoTargetDuration={autoTargetDuration}
        onAutoTargetDurationChange={onAutoTargetDurationChange}
        autoNumPlans={autoNumPlans}
        onAutoNumPlansChange={onAutoNumPlansChange}
        autoBgmMixEnabled={autoBgmMixEnabled}
        onAutoBgmMixEnabledChange={onAutoBgmMixEnabledChange}
        autoBgmPlanPolicy={autoBgmPlanPolicy}
        onAutoBgmPlanPolicyChange={onAutoBgmPlanPolicyChange}
        autoBgmTrackFilename={autoBgmTrackFilename}
        onAutoBgmTrackFilenameChange={onAutoBgmTrackFilenameChange}
        showAutoCustomBgmConfig={showAutoCustomBgmConfig}
        autoCustomBgmEnabled={autoCustomBgmEnabled}
        onAutoCustomBgmEnabledChange={onAutoCustomBgmEnabledChange}
        autoCustomBgmTrackIds={autoCustomBgmTrackIds}
        onToggleAutoCustomBgmTrack={onToggleAutoCustomBgmTrack}
        autoCustomBgmVolumeByTrackId={autoCustomBgmVolumeByTrackId}
        onAutoCustomBgmTrackVolumeChange={onAutoCustomBgmTrackVolumeChange}
        autoCustomBgmTimelineSegments={autoCustomBgmTimelineSegments}
        onAddAutoCustomBgmTimelineSegment={onAddAutoCustomBgmTimelineSegment}
        onRemoveAutoCustomBgmTimelineSegment={onRemoveAutoCustomBgmTimelineSegment}
        onUpdateAutoCustomBgmTimelineSegment={onUpdateAutoCustomBgmTimelineSegment}
        showVoiceoverBgmConfig={showVoiceoverBgmConfig}
        voiceoverBgmEnabled={voiceoverBgmEnabled}
        onVoiceoverBgmEnabledChange={onVoiceoverBgmEnabledChange}
        bgmTracksForVoiceover={bgmTracksForVoiceover ?? bgmTracks}
        bgmListErrorForVoiceover={bgmListErrorForVoiceover || bgmListError}
        selectedVoiceoverBgmTrackIds={selectedVoiceoverBgmTrackIds}
        onToggleVoiceoverBgmTrack={onToggleVoiceoverBgmTrack}
        voiceoverBgmVolumeByTrackId={voiceoverBgmVolumeByTrackId}
        onVoiceoverBgmTrackVolumeChange={onVoiceoverBgmTrackVolumeChange}
        voiceoverBgmTimelineSegments={voiceoverBgmTimelineSegments}
        onAddVoiceoverBgmTimelineSegment={onAddVoiceoverBgmTimelineSegment}
        onRemoveVoiceoverBgmTimelineSegment={onRemoveVoiceoverBgmTimelineSegment}
        onUpdateVoiceoverBgmTimelineSegment={onUpdateVoiceoverBgmTimelineSegment}
        autoUseTimelineEngine={autoUseTimelineEngine}
        onAutoUseTimelineEngineChange={onAutoUseTimelineEngineChange}
        processingProfileLocked={processingProfileLocked}
        processingProfileHint={processingProfileHint}
        autoContentStyle={autoContentStyle}
        onAutoContentStyleChange={onAutoContentStyleChange}
        autoEventsAdvancedEnabled={autoEventsAdvancedEnabled}
        onAutoEventsAdvancedEnabledChange={onAutoEventsAdvancedEnabledChange}
        autoEventsMaxClipsPerBatch={autoEventsMaxClipsPerBatch}
        onAutoEventsMaxClipsPerBatchChange={onAutoEventsMaxClipsPerBatchChange}
        autoEventsMaxCharsPerBatch={autoEventsMaxCharsPerBatch}
        onAutoEventsMaxCharsPerBatchChange={onAutoEventsMaxCharsPerBatchChange}
        autoEventsBatchOverlapClips={autoEventsBatchOverlapClips}
        onAutoEventsBatchOverlapClipsChange={onAutoEventsBatchOverlapClipsChange}
        autoEventsMaxBatches={autoEventsMaxBatches}
        onAutoEventsMaxBatchesChange={onAutoEventsMaxBatchesChange}
        recommendedProfile={recommendedProfile}
        estimatedBatches={estimatedBatches}
        estimatedSeconds={estimatedSeconds}
        estimatedTotalClips={estimatedTotalClips}
        onResetAdvancedToRecommended={onResetAdvancedToRecommended}
        autoExplain={autoExplain}
        onAutoExplainChange={onAutoExplainChange}
        onGeneratePlans={onGeneratePlans}
        autoPlanLogs={autoPlanLogs}
        autoPlanElapsedSec={autoPlanElapsedSec}
        autoPlanStage={autoPlanStage}
        autoPlanStagePercent={autoPlanStagePercent}
      />

      {activePlan && (
        <AutoEditPlanWorkspace
          activePlan={activePlan}
          onDeselect={() => setActivePlan(null)}
          detailEditMode={detailEditMode}
          setDetailEditMode={setDetailEditMode}
          detailDraft={detailDraft}
          setDetailDraft={setDetailDraft}
          setCustomPlanById={setCustomPlanById}
          clipMetaByClip={clipMetaByClip}
          setSelectedPreview={setSelectedPreview}
        />
      )}

      {autoPlans.length > 0 && (
        <>
          {candidatesSectionTitle ? (
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
              {candidatesSectionTitle}
            </p>
          ) : null}
          <AutoEditCandidatesSection
          autoPlans={autoPlans}
          subtitleEnabled={subtitleEnabled}
          autoExpandedPlanIds={autoExpandedPlanIds}
          onTogglePlanExpand={onTogglePlanExpand}
          clipMetaByClip={clipMetaByClip}
          selectedPreview={selectedPreview}
          setSelectedPreview={setSelectedPreview}
          customPlanById={customPlanById}
          activePlanId={activePlan?.plan.plan_id ?? null}
          onSelectPlan={selectPlan}
          onOpenFullscreenPlan={(plan, index) => setFullscreenPlan({ plan, index })}
          onRealizePlan={onRealizePlan}
          autoRealizingId={autoRealizingId}
          autoRealizeMsg={autoRealizeMsg}
          autoRealizeDownloads={autoRealizeDownloads}
          autoJianyingDraftExportingId={autoJianyingDraftExportingId}
          autoJianyingDraftDownloads={autoJianyingDraftDownloads}
          onExportJianyingDraft={onExportJianyingDraft}
        />
        </>
      )}

      {fullscreenPlan ? (
        <AutoEditDetailModal
          detailPlan={fullscreenPlan}
          onClose={() => setFullscreenPlan(null)}
          detailEditMode={detailEditMode}
          setDetailEditMode={setDetailEditMode}
          detailDraft={detailDraft}
          setDetailDraft={setDetailDraft}
          setCustomPlanById={setCustomPlanById}
          clipMetaByClip={clipMetaByClip}
          setSelectedPreview={setSelectedPreview}
        />
      ) : null}
    </>
  )
}
