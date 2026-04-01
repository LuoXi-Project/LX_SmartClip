import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AutoEditPlanApi, AutoEditMode, Video } from './api'
import type { Segment } from '@/app/match/_components/types'
import type { ExportMode, SubtitleStyle } from '@/lib/subtitle-types'
import { DEFAULT_SUBTITLE_STYLE } from '@/lib/subtitle-types'

export type { Video }

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
  /** 手动匹配 / 自动一键成片 */
  matchMode: 'manual' | 'auto'
  /** 段落 id 递增，与 segments 一并持久化，避免返回页面后 id 冲突 */
  segmentCounter: number
  autoPrompt: string
  autoMode: AutoEditMode
  autoTargetDuration: number | ''
  autoNumPlans: number
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
  setMatchMode: (mode: 'manual' | 'auto') => void
  setMatchSegmentCounter: (n: number | ((prev: number) => number)) => void
  setAutoPrompt: (v: string) => void
  setAutoMode: (m: AutoEditMode) => void
  setAutoTargetDuration: (v: number | '') => void
  setAutoNumPlans: (n: number) => void
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
      segmentCounter: 0,
      autoPrompt: '',
      autoMode: 'auto' as AutoEditMode,
      autoTargetDuration: 60 as number | '',
      autoNumPlans: 3,
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
      setMatchSegmentCounter: (n) =>
        set((state) => ({
          segmentCounter: typeof n === 'function' ? n(state.segmentCounter) : n,
        })),
      setAutoPrompt: (autoPrompt) => set({ autoPrompt }),
      setAutoMode: (autoMode) => set({ autoMode }),
      setAutoTargetDuration: (autoTargetDuration) => set({ autoTargetDuration }),
      setAutoNumPlans: (autoNumPlans) => set({ autoNumPlans }),
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
          segmentCounter: 0,
        }),
    }),
    {
      name: 'lx-match-state',
      version: 2,
      migrate: (persistedState) => {
        const p = (persistedState || {}) as Partial<MatchPageState>
        const merged: Partial<MatchPageState> = {
          matchMode: 'manual',
          segmentCounter: 0,
          autoPrompt: '',
          autoMode: 'auto',
          autoTargetDuration: 60,
          autoNumPlans: 3,
          autoPlans: [],
          autoRealizeDownloads: {},
          autoExpandedPlanIds: [],
          autoPlanLogs: [],
          ...p,
        }
        if (merged.matchMode !== 'manual' && merged.matchMode !== 'auto') merged.matchMode = 'manual'
        if (typeof merged.segmentCounter !== 'number' || merged.segmentCounter < 0) merged.segmentCounter = 0
        if (!Array.isArray(merged.autoPlans)) merged.autoPlans = []
        if (!merged.autoRealizeDownloads || typeof merged.autoRealizeDownloads !== 'object') {
          merged.autoRealizeDownloads = {}
        }
        if (!Array.isArray(merged.autoExpandedPlanIds)) merged.autoExpandedPlanIds = []
        if (!Array.isArray(merged.autoPlanLogs)) merged.autoPlanLogs = []
        return mergeLegacyAutoEditCache(merged)
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
          if (state.matchMode !== 'manual' && state.matchMode !== 'auto') state.matchMode = 'manual'
          if (typeof state.segmentCounter !== 'number' || state.segmentCounter < 0) state.segmentCounter = 0
          if (!Array.isArray(state.autoPlans)) state.autoPlans = []
          if (!state.autoRealizeDownloads || typeof state.autoRealizeDownloads !== 'object') {
            state.autoRealizeDownloads = {}
          }
          if (!Array.isArray(state.autoExpandedPlanIds)) state.autoExpandedPlanIds = []
          if (!Array.isArray(state.autoPlanLogs)) state.autoPlanLogs = []
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