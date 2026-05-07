import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AutoEditPlanApi, AutoEditMode, Video } from './api'
import type { Segment } from '@/app/match/_components/types'
import type { MatchWorkspaceMode } from '@/app/match/_components/matchModeTypes'
import { normalizeMatchWorkspaceMode } from '@/app/match/_components/matchModeTypes'
import type { ExportMode, SubtitleStyle } from '@/lib/subtitle-types'
import { DEFAULT_SUBTITLE_STYLE } from '@/lib/subtitle-types'

export type { Video }
export type TemplatePresetSource = 'library' | 'replica'

export interface TtsHistoryItem {
  id: string
  text: string
  voice: string
  rate: string
  volume: string
  filename: string
}

/** 与智能剪辑页 localStorage 旧版自动成片键一致，仅用于一次性 migrate 合并 */
export const LEGACY_AUTO_EDIT_CACHE_KEY = 'lx-auto-edit-state-v1'

export interface MatchPageState {
  segments: Segment[]
  globalQuery: string
  selectedVideoIds: string[]
  topK: number
  topN: number
  subtitleEnabled: boolean
  subtitleStyle: SubtitleStyle
  exportMode: ExportMode
  /** 工作区：手动 / 口播快剪 / 自动成片实验 / 模板剪辑 */
  matchMode: MatchWorkspaceMode
  /** 模板剪辑预设 */
  templatePreset: string
  /** 模板选择来源：模板库 / 链接复刻锁定 */
  templatePresetSource: TemplatePresetSource
  /** 自动一键成片页面内：是否启用模板剪辑(v4) */
  autoTemplateEnabled: boolean
  /** 段落 id 递增，与 segments 一并持久化，避免返回页面后 id 冲突 */
  segmentCounter: number
  autoPrompt: string
  autoMode: AutoEditMode
  autoTargetDuration: number | ''
  autoNumPlans: number
  /** 成片导出时是否叠加 BGM 混音 */
  autoBgmMixEnabled: boolean
  /** 规划阶段传给后端的 bgm_policy，影响 LLM 方案中的 bgm 字段倾向 */
  autoBgmPlanPolicy: 'auto' | 'none' | 'user' | 'ai'
  /** 成片时曲目：空字符串表示自动选曲（库内/manifest/方案内 track） */
  autoBgmTrackFilename: string
  /** 低侵入升级：是否启用事件级时间轴新引擎 */
  autoUseTimelineEngine: boolean
  /** 调试开关：生成可解释中间产物 */
  autoExplain: boolean
  /** Timeline Engine 任务级参数预设（命中后端默认档位） */
  autoContentStyle: 'generic' | 'ecommerce' | 'voiceover' | 'commentary'
  /** 是否启用高级参数覆盖 */
  autoEventsAdvancedEnabled: boolean
  autoEventsMaxClipsPerBatch: number | ''
  autoEventsMaxCharsPerBatch: number | ''
  autoEventsBatchOverlapClips: number | ''
  autoEventsMaxBatches: number | ''
  /** 链接复刻：已确认的模板引导（注入手动匹配文案 / 一键成片诉求） */
  replicaTemplateGuide: string
  /** 链接复刻：模板类型，驱动一键成片模板预设 */
  replicaTemplateType: 'short_video' | 'film_commentary' | 'scene_story' | ''
  autoPlans: AutoEditPlanApi[]
  autoRealizeDownloads: Record<string, { filename: string; url: string }>
  autoExpandedPlanIds: string[]
  autoPlanLogs: string[]
  setMatchSegments: (segments: Segment[]) => void
  setMatchGlobalQuery: (q: string) => void
  setMatchSelectedVideoIds: (ids: string[]) => void
  setMatchTopK: (v: number) => void
  setMatchTopN: (v: number) => void
  setMatchSubtitleEnabled: (v: boolean) => void
  setMatchSubtitleStyle: (s: SubtitleStyle) => void
  setMatchExportMode: (m: ExportMode) => void
  setMatchMode: (mode: MatchWorkspaceMode) => void
  setTemplatePreset: (p: string) => void
  setTemplatePresetSource: (s: TemplatePresetSource) => void
  setAutoTemplateEnabled: (v: boolean) => void
  setMatchSegmentCounter: (n: number | ((prev: number) => number)) => void
  setAutoPrompt: (v: string) => void
  setAutoMode: (m: AutoEditMode) => void
  setAutoTargetDuration: (v: number | '') => void
  setAutoNumPlans: (n: number) => void
  setAutoBgmMixEnabled: (v: boolean) => void
  setAutoBgmPlanPolicy: (p: 'auto' | 'none' | 'user' | 'ai') => void
  setAutoBgmTrackFilename: (name: string) => void
  setAutoUseTimelineEngine: (v: boolean) => void
  setAutoExplain: (v: boolean) => void
  setAutoContentStyle: (v: 'generic' | 'ecommerce' | 'voiceover' | 'commentary') => void
  setAutoEventsAdvancedEnabled: (v: boolean) => void
  setAutoEventsMaxClipsPerBatch: (v: number | '') => void
  setAutoEventsMaxCharsPerBatch: (v: number | '') => void
  setAutoEventsBatchOverlapClips: (v: number | '') => void
  setAutoEventsMaxBatches: (v: number | '') => void
  setReplicaTemplateGuide: (v: string) => void
  setReplicaTemplateType: (v: 'short_video' | 'film_commentary' | 'scene_story' | '') => void
  setAutoPlans: (plans: AutoEditPlanApi[]) => void
  setAutoRealizeDownloads: (
    fn:
      | Record<string, { filename: string; url: string }>
      | ((prev: Record<string, { filename: string; url: string }>) => Record<string, { filename: string; url: string }>)
  ) => void
  setAutoExpandedPlanIds: (fn: string[] | ((prev: string[]) => string[])) => void
  setAutoPlanLogs: (fn: string[] | ((prev: string[]) => string[])) => void
  clearMatchState: () => void
}

/** 与 persist partialize 一致，仅含可序列化字段（不含 action） */
export type MatchPersistedSlice = Pick<
  MatchPageState,
  | 'segments'
  | 'globalQuery'
  | 'selectedVideoIds'
  | 'topK'
  | 'topN'
  | 'subtitleEnabled'
  | 'subtitleStyle'
  | 'exportMode'
  | 'matchMode'
  | 'templatePreset'
  | 'templatePresetSource'
  | 'autoTemplateEnabled'
  | 'segmentCounter'
  | 'autoPrompt'
  | 'autoMode'
  | 'autoTargetDuration'
  | 'autoNumPlans'
  | 'autoBgmMixEnabled'
  | 'autoBgmPlanPolicy'
  | 'autoBgmTrackFilename'
  | 'autoUseTimelineEngine'
  | 'autoExplain'
  | 'autoContentStyle'
  | 'autoEventsAdvancedEnabled'
  | 'autoEventsMaxClipsPerBatch'
  | 'autoEventsMaxCharsPerBatch'
  | 'autoEventsBatchOverlapClips'
  | 'autoEventsMaxBatches'
  | 'replicaTemplateGuide'
  | 'replicaTemplateType'
  | 'autoPlans'
  | 'autoRealizeDownloads'
  | 'autoExpandedPlanIds'
  | 'autoPlanLogs'
>

export interface TtsPageState {
  ttsHistory: TtsHistoryItem[]
  ttsText: string
  ttsSelectedVoice: string
  ttsRate: string
  ttsVolume: string
  setTtsHistory: (h: TtsHistoryItem[]) => void
  addTtsHistory: (item: TtsHistoryItem) => void
  setTtsText: (t: string) => void
  setTtsSelectedVoice: (v: string) => void
  setTtsRate: (r: string) => void
  setTtsVolume: (v: string) => void
  clearTtsHistory: () => void
}

export interface AppState {
  videos: Video[]
  setVideos: (videos: Video[]) => void
  addVideo: (video: Video) => void
  removeVideo: (id: string) => void
  backendStatus: 'connected' | 'disconnected' | 'loading'
  setBackendStatus: (status: 'connected' | 'disconnected' | 'loading') => void
}

export const useAppStore = create<AppState>((set) => ({
  videos: [],
  setVideos: (videos) => set({ videos }),
  addVideo: (video) => set((state) => ({ videos: [video, ...state.videos] })),
  removeVideo: (id) =>
    set((state) => ({
      videos: state.videos.filter((v) => v.id !== id),
    })),
  backendStatus: 'loading',
  setBackendStatus: (status) => set({ backendStatus: status }),
}))

function mergeLegacyAutoEditCache(persisted: Partial<MatchPageState>): Partial<MatchPageState> {
  if (typeof window === 'undefined') return persisted
  try {
    const raw = window.localStorage.getItem(LEGACY_AUTO_EDIT_CACHE_KEY)
    if (!raw) return persisted
    const j = JSON.parse(raw) as Record<string, unknown>
    const next = { ...persisted }
    const curPlans = Array.isArray(next.autoPlans) ? next.autoPlans : []
    const legPlans = j.autoPlans
    if (curPlans.length === 0 && Array.isArray(legPlans) && legPlans.length > 0) {
      next.autoPlans = legPlans as AutoEditPlanApi[]
    }
    if (typeof j.autoPrompt === 'string' && !next.autoPrompt?.trim()) next.autoPrompt = j.autoPrompt
    if (j.autoMode === 'auto' || j.autoMode === 'voiceover' || j.autoMode === 'original') {
      next.autoMode = j.autoMode as AutoEditMode
    }
    if (typeof j.autoTargetDuration === 'number' || j.autoTargetDuration === '') {
      next.autoTargetDuration = j.autoTargetDuration as number | ''
    }
    if (typeof j.autoNumPlans === 'number') next.autoNumPlans = j.autoNumPlans as number
    if (
      (!next.autoRealizeDownloads || Object.keys(next.autoRealizeDownloads).length === 0) &&
      j.autoRealizeDownloads &&
      typeof j.autoRealizeDownloads === 'object'
    ) {
      next.autoRealizeDownloads = j.autoRealizeDownloads as Record<string, { filename: string; url: string }>
    }
    if (
      (!next.autoExpandedPlanIds || next.autoExpandedPlanIds.length === 0) &&
      Array.isArray(j.autoExpandedPlanIds)
    ) {
      next.autoExpandedPlanIds = j.autoExpandedPlanIds as string[]
    }
    if ((!next.autoPlanLogs || next.autoPlanLogs.length === 0) && Array.isArray(j.autoPlanLogs)) {
      next.autoPlanLogs = j.autoPlanLogs as string[]
    }
    return next
  } catch {
    return persisted
  }
}

export const useMatchStore = create<MatchPageState>()(
  persist(
    (set) => ({
      segments: [],
      globalQuery: '',
      selectedVideoIds: [],
      topK: 12,
      topN: 5,
      subtitleEnabled: false,
      subtitleStyle: DEFAULT_SUBTITLE_STYLE,
      exportMode: 'zip' as ExportMode,
      matchMode: 'manual' as const,
      templatePreset: 'ecommerce',
      templatePresetSource: 'library' as const,
      autoTemplateEnabled: false,
      segmentCounter: 0,
      autoPrompt: '',
      autoMode: 'auto' as AutoEditMode,
      autoTargetDuration: 60 as number | '',
      autoNumPlans: 3,
      autoBgmMixEnabled: false,
      autoBgmPlanPolicy: 'auto' as const,
      autoBgmTrackFilename: '',
      autoUseTimelineEngine: false,
      autoExplain: false,
      autoContentStyle: 'generic',
      autoEventsAdvancedEnabled: false,
      autoEventsMaxClipsPerBatch: '',
      autoEventsMaxCharsPerBatch: '',
      autoEventsBatchOverlapClips: '',
      autoEventsMaxBatches: '',
      replicaTemplateGuide: '',
      replicaTemplateType: '',
      autoPlans: [] as AutoEditPlanApi[],
      autoRealizeDownloads: {} as Record<string, { filename: string; url: string }>,
      autoExpandedPlanIds: [] as string[],
      autoPlanLogs: [] as string[],
      setMatchSegments: (segments) => set({ segments }),
      setMatchGlobalQuery: (globalQuery) => set({ globalQuery }),
      setMatchSelectedVideoIds: (selectedVideoIds) => set({ selectedVideoIds }),
      setMatchTopK: (topK) => set({ topK }),
      setMatchTopN: (topN) => set({ topN }),
      setMatchSubtitleEnabled: (subtitleEnabled) => set({ subtitleEnabled }),
      setMatchSubtitleStyle: (subtitleStyle) => set({ subtitleStyle }),
      setMatchExportMode: (exportMode) => set({ exportMode }),
      setMatchMode: (matchMode) => set({ matchMode }),
      setTemplatePreset: (templatePreset) => set({ templatePreset }),
      setTemplatePresetSource: (templatePresetSource) => set({ templatePresetSource }),
      setAutoTemplateEnabled: (autoTemplateEnabled) => set({ autoTemplateEnabled }),
      setMatchSegmentCounter: (n) =>
        set((state) => ({
          segmentCounter: typeof n === 'function' ? n(state.segmentCounter) : n,
        })),
      setAutoPrompt: (autoPrompt) => set({ autoPrompt }),
      setAutoMode: (autoMode) => set({ autoMode }),
      setAutoTargetDuration: (autoTargetDuration) => set({ autoTargetDuration }),
      setAutoNumPlans: (autoNumPlans) => set({ autoNumPlans }),
      setAutoBgmMixEnabled: (autoBgmMixEnabled) => set({ autoBgmMixEnabled }),
      setAutoBgmPlanPolicy: (autoBgmPlanPolicy) => set({ autoBgmPlanPolicy }),
      setAutoBgmTrackFilename: (autoBgmTrackFilename) => set({ autoBgmTrackFilename }),
      setAutoUseTimelineEngine: (autoUseTimelineEngine) => set({ autoUseTimelineEngine }),
      setAutoExplain: (autoExplain) => set({ autoExplain }),
      setAutoContentStyle: (autoContentStyle) => set({ autoContentStyle }),
      setAutoEventsAdvancedEnabled: (autoEventsAdvancedEnabled) => set({ autoEventsAdvancedEnabled }),
      setAutoEventsMaxClipsPerBatch: (autoEventsMaxClipsPerBatch) => set({ autoEventsMaxClipsPerBatch }),
      setAutoEventsMaxCharsPerBatch: (autoEventsMaxCharsPerBatch) => set({ autoEventsMaxCharsPerBatch }),
      setAutoEventsBatchOverlapClips: (autoEventsBatchOverlapClips) => set({ autoEventsBatchOverlapClips }),
      setAutoEventsMaxBatches: (autoEventsMaxBatches) => set({ autoEventsMaxBatches }),
      setReplicaTemplateGuide: (replicaTemplateGuide) => set({ replicaTemplateGuide }),
      setReplicaTemplateType: (replicaTemplateType) => set({ replicaTemplateType }),
      setAutoPlans: (autoPlans) => set({ autoPlans }),
      setAutoRealizeDownloads: (fn) =>
        set((state) => ({
          autoRealizeDownloads: typeof fn === 'function' ? fn(state.autoRealizeDownloads) : fn,
        })),
      setAutoExpandedPlanIds: (fn) =>
        set((state) => ({
          autoExpandedPlanIds: typeof fn === 'function' ? fn(state.autoExpandedPlanIds) : fn,
        })),
      setAutoPlanLogs: (fn) =>
        set((state) => ({
          autoPlanLogs: typeof fn === 'function' ? fn(state.autoPlanLogs) : fn,
        })),
      clearMatchState: () =>
        set({
          segments: [],
          globalQuery: '',
          selectedVideoIds: [],
          topK: 12,
          topN: 5,
          subtitleEnabled: false,
          subtitleStyle: DEFAULT_SUBTITLE_STYLE,
          exportMode: 'zip',
          templatePreset: 'ecommerce',
          templatePresetSource: 'library',
          autoTemplateEnabled: false,
          segmentCounter: 0,
          replicaTemplateGuide: '',
          replicaTemplateType: '',
        }),
    }),
    {
      name: 'lx-match-state',
      version: 5,
      /** 只持久化数据字段，避免把函数/未知键写进 localStorage */
      partialize: (state): MatchPersistedSlice => ({
        segments: state.segments,
        globalQuery: state.globalQuery,
        selectedVideoIds: state.selectedVideoIds,
        topK: state.topK,
        topN: state.topN,
        subtitleEnabled: state.subtitleEnabled,
        subtitleStyle: state.subtitleStyle,
        exportMode: state.exportMode,
        matchMode: state.matchMode,
        templatePreset: state.templatePreset,
        templatePresetSource: state.templatePresetSource,
        autoTemplateEnabled: state.autoTemplateEnabled,
        segmentCounter: state.segmentCounter,
        autoPrompt: state.autoPrompt,
        autoMode: state.autoMode,
        autoTargetDuration: state.autoTargetDuration,
        autoNumPlans: state.autoNumPlans,
        autoBgmMixEnabled: state.autoBgmMixEnabled,
        autoBgmPlanPolicy: state.autoBgmPlanPolicy,
        autoBgmTrackFilename: state.autoBgmTrackFilename,
        autoUseTimelineEngine: state.autoUseTimelineEngine,
        autoExplain: state.autoExplain,
        autoContentStyle: state.autoContentStyle,
        autoEventsAdvancedEnabled: state.autoEventsAdvancedEnabled,
        autoEventsMaxClipsPerBatch: state.autoEventsMaxClipsPerBatch,
        autoEventsMaxCharsPerBatch: state.autoEventsMaxCharsPerBatch,
        autoEventsBatchOverlapClips: state.autoEventsBatchOverlapClips,
        autoEventsMaxBatches: state.autoEventsMaxBatches,
        replicaTemplateGuide: state.replicaTemplateGuide,
        replicaTemplateType: state.replicaTemplateType,
        autoPlans: state.autoPlans,
        autoRealizeDownloads: state.autoRealizeDownloads,
        autoExpandedPlanIds: state.autoExpandedPlanIds,
        autoPlanLogs: state.autoPlanLogs,
      }),
      /** persisted 中若存在与 action 同名的脏键，会覆盖函数导致「xxx is not a function」 */
      merge: (persistedState, currentState) => ({
        ...currentState,
        ...(persistedState ?? {}),
        ...Object.fromEntries(Object.entries(currentState).filter(([, v]) => typeof v === 'function')),
      }),
      migrate: (persistedState, _oldVersion): MatchPersistedSlice => {
        const p = (persistedState || {}) as Partial<MatchPersistedSlice>
        const merged: Partial<MatchPersistedSlice> = {
          matchMode: 'manual',
          templatePreset: 'ecommerce',
          templatePresetSource: 'library',
          autoTemplateEnabled: false,
          segmentCounter: 0,
          autoPrompt: '',
          autoMode: 'auto',
          autoTargetDuration: 60,
          autoNumPlans: 3,
          autoUseTimelineEngine: false,
          autoExplain: false,
          autoContentStyle: 'generic',
          autoEventsAdvancedEnabled: false,
          autoEventsMaxClipsPerBatch: '',
          autoEventsMaxCharsPerBatch: '',
          autoEventsBatchOverlapClips: '',
          autoEventsMaxBatches: '',
          autoPlans: [],
          autoRealizeDownloads: {},
          autoExpandedPlanIds: [],
          autoPlanLogs: [],
          ...p,
        }
        merged.matchMode = normalizeMatchWorkspaceMode(merged.matchMode)
        if (typeof merged.templatePreset !== 'string' || !merged.templatePreset.trim()) {
          merged.templatePreset = 'ecommerce'
        }
        if (merged.templatePresetSource !== 'library' && merged.templatePresetSource !== 'replica') {
          merged.templatePresetSource = 'library'
        }
        if (typeof merged.autoTemplateEnabled !== 'boolean') merged.autoTemplateEnabled = false
        if (typeof merged.segmentCounter !== 'number' || merged.segmentCounter < 0) merged.segmentCounter = 0
        if (!Array.isArray(merged.segments)) merged.segments = []
        if (typeof merged.globalQuery !== 'string') merged.globalQuery = ''
        if (!Array.isArray(merged.selectedVideoIds)) merged.selectedVideoIds = []
        if (typeof merged.topK !== 'number') merged.topK = 12
        if (typeof merged.topN !== 'number') merged.topN = 5
        if (typeof merged.subtitleEnabled !== 'boolean') merged.subtitleEnabled = false
        if (!merged.subtitleStyle || typeof merged.subtitleStyle !== 'object') merged.subtitleStyle = DEFAULT_SUBTITLE_STYLE
        const em = merged.exportMode
        if (
          em !== 'zip' &&
          em !== 'subtitle' &&
          em !== 'original' &&
          em !== 'jianying_tts' &&
          em !== 'jianying_original'
        ) {
          merged.exportMode = 'zip'
        }
        if (!Array.isArray(merged.autoPlans)) merged.autoPlans = []
        if (!merged.autoRealizeDownloads || typeof merged.autoRealizeDownloads !== 'object') {
          merged.autoRealizeDownloads = {}
        }
        if (!Array.isArray(merged.autoExpandedPlanIds)) merged.autoExpandedPlanIds = []
        if (!Array.isArray(merged.autoPlanLogs)) merged.autoPlanLogs = []
        if (typeof merged.autoBgmMixEnabled !== 'boolean') merged.autoBgmMixEnabled = false
        const pol = merged.autoBgmPlanPolicy
        if (pol !== 'auto' && pol !== 'none' && pol !== 'user' && pol !== 'ai') {
          merged.autoBgmPlanPolicy = 'auto'
        }
        if (typeof merged.autoBgmTrackFilename !== 'string') merged.autoBgmTrackFilename = ''
        if (typeof merged.autoUseTimelineEngine !== 'boolean') merged.autoUseTimelineEngine = false
        if (typeof merged.autoExplain !== 'boolean') merged.autoExplain = false
        if (
          merged.autoContentStyle !== 'generic' &&
          merged.autoContentStyle !== 'ecommerce' &&
          merged.autoContentStyle !== 'voiceover' &&
          merged.autoContentStyle !== 'commentary'
        ) {
          merged.autoContentStyle = 'generic'
        }
        if (typeof merged.autoEventsAdvancedEnabled !== 'boolean') merged.autoEventsAdvancedEnabled = false
        if (typeof merged.autoEventsMaxClipsPerBatch !== 'number' && merged.autoEventsMaxClipsPerBatch !== '') merged.autoEventsMaxClipsPerBatch = ''
        if (typeof merged.autoEventsMaxCharsPerBatch !== 'number' && merged.autoEventsMaxCharsPerBatch !== '') merged.autoEventsMaxCharsPerBatch = ''
        if (typeof merged.autoEventsBatchOverlapClips !== 'number' && merged.autoEventsBatchOverlapClips !== '') merged.autoEventsBatchOverlapClips = ''
        if (typeof merged.autoEventsMaxBatches !== 'number' && merged.autoEventsMaxBatches !== '') merged.autoEventsMaxBatches = ''
        if (typeof merged.replicaTemplateGuide !== 'string') merged.replicaTemplateGuide = ''
        if (typeof (merged as any).replicaTemplateType !== 'string') (merged as any).replicaTemplateType = ''
        return mergeLegacyAutoEditCache(merged) as MatchPersistedSlice
      },
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.segments = (state.segments || []).map((s) => ({
            ...s,
            ttsLoading: false,
            matchLoading: false,
            ttsError: '',
            matchError: '',
          }))
          state.matchMode = normalizeMatchWorkspaceMode(state.matchMode)
          if (typeof state.templatePreset !== 'string' || !state.templatePreset.trim()) {
            state.templatePreset = 'ecommerce'
          }
          if (state.templatePresetSource !== 'library' && state.templatePresetSource !== 'replica') {
            state.templatePresetSource = 'library'
          }
          if (typeof state.autoTemplateEnabled !== 'boolean') state.autoTemplateEnabled = false
          if (typeof state.segmentCounter !== 'number' || state.segmentCounter < 0) state.segmentCounter = 0
          if (!Array.isArray(state.autoPlans)) state.autoPlans = []
          if (!state.autoRealizeDownloads || typeof state.autoRealizeDownloads !== 'object') {
            state.autoRealizeDownloads = {}
          }
          if (!Array.isArray(state.autoExpandedPlanIds)) state.autoExpandedPlanIds = []
          if (!Array.isArray(state.autoPlanLogs)) state.autoPlanLogs = []
          if (typeof state.autoBgmMixEnabled !== 'boolean') state.autoBgmMixEnabled = false
          const pol = state.autoBgmPlanPolicy
          if (pol !== 'auto' && pol !== 'none' && pol !== 'user' && pol !== 'ai') {
            state.autoBgmPlanPolicy = 'auto'
          }
          if (typeof state.autoBgmTrackFilename !== 'string') state.autoBgmTrackFilename = ''
          if (typeof state.autoUseTimelineEngine !== 'boolean') state.autoUseTimelineEngine = false
          if (typeof state.autoExplain !== 'boolean') state.autoExplain = false
          if (
            state.autoContentStyle !== 'generic' &&
            state.autoContentStyle !== 'ecommerce' &&
            state.autoContentStyle !== 'voiceover' &&
            state.autoContentStyle !== 'commentary'
          ) {
            state.autoContentStyle = 'generic'
          }
          if (typeof state.autoEventsAdvancedEnabled !== 'boolean') state.autoEventsAdvancedEnabled = false
          if (typeof state.autoEventsMaxClipsPerBatch !== 'number' && state.autoEventsMaxClipsPerBatch !== '') state.autoEventsMaxClipsPerBatch = ''
          if (typeof state.autoEventsMaxCharsPerBatch !== 'number' && state.autoEventsMaxCharsPerBatch !== '') state.autoEventsMaxCharsPerBatch = ''
          if (typeof state.autoEventsBatchOverlapClips !== 'number' && state.autoEventsBatchOverlapClips !== '') state.autoEventsBatchOverlapClips = ''
          if (typeof state.autoEventsMaxBatches !== 'number' && state.autoEventsMaxBatches !== '') state.autoEventsMaxBatches = ''
          if (typeof state.replicaTemplateGuide !== 'string') state.replicaTemplateGuide = ''
          if (typeof (state as any).replicaTemplateType !== 'string') (state as any).replicaTemplateType = ''
        }
      },
    }
  )
)

export const useTtsStore = create<TtsPageState>()(
  persist(
    (set) => ({
      ttsHistory: [],
      ttsText: '',
      ttsSelectedVoice: '',
      ttsRate: '+0%',
      ttsVolume: '+0%',
      setTtsHistory: (ttsHistory) => set({ ttsHistory }),
      addTtsHistory: (item) =>
        set((state) => ({ ttsHistory: [item, ...state.ttsHistory].slice(0, 50) })),
      setTtsText: (ttsText) => set({ ttsText }),
      setTtsSelectedVoice: (ttsSelectedVoice) => set({ ttsSelectedVoice }),
      setTtsRate: (ttsRate) => set({ ttsRate }),
      setTtsVolume: (ttsVolume) => set({ ttsVolume }),
      clearTtsHistory: () => set({ ttsHistory: [] }),
    }),
    { name: 'lx-tts-state' }
  )
)