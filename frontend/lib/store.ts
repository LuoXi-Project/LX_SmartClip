import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Video } from './api'
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

export interface MatchPageState {
  segments: Segment[]
  globalQuery: string
  selectedVideoIds: string[]
  topK: number
  topN: number
  subtitleEnabled: boolean
  subtitleStyle: SubtitleStyle
  exportMode: ExportMode
  setMatchSegments: (segments: Segment[]) => void
  setMatchGlobalQuery: (q: string) => void
  setMatchSelectedVideoIds: (ids: string[]) => void
  setMatchTopK: (v: number) => void
  setMatchTopN: (v: number) => void
  setMatchSubtitleEnabled: (v: boolean) => void
  setMatchSubtitleStyle: (s: SubtitleStyle) => void
  setMatchExportMode: (m: ExportMode) => void
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
      setMatchSegments: (segments) => set({ segments }),
      setMatchGlobalQuery: (globalQuery) => set({ globalQuery }),
      setMatchSelectedVideoIds: (selectedVideoIds) => set({ selectedVideoIds }),
      setMatchTopK: (topK) => set({ topK }),
      setMatchTopN: (topN) => set({ topN }),
      setMatchSubtitleEnabled: (subtitleEnabled) => set({ subtitleEnabled }),
      setMatchSubtitleStyle: (subtitleStyle) => set({ subtitleStyle }),
      setMatchExportMode: (exportMode) => set({ exportMode }),
      clearMatchState: () => set({
        segments: [],
        globalQuery: '',
        selectedVideoIds: [],
        topK: 12,
        topN: 5,
        subtitleEnabled: false,
        subtitleStyle: DEFAULT_SUBTITLE_STYLE,
        exportMode: 'zip',
      }),
    }),
    {
      name: 'lx-match-state',
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.segments = state.segments.map((s) => ({
            ...s,
            ttsLoading: false,
            matchLoading: false,
            ttsError: '',
            matchError: '',
          }))
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