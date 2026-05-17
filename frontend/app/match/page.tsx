'use client'

import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import Link from 'next/link'
import {
  AlertCircle, Loader2,
} from 'lucide-react'
import apiClient, {
  API_BASE_URL,
  bgmApi,
  exportApi,
  ttsApi,
  subtitleApi,
  formatFastApiDetail,
  type MatchClip,
  type Video,
  autoEditApi,
  type AutoEditPlanApi,
  type AutoEditBgmPlanApi,
  type BgmTrack,
  type TtsVideoAlignConfigApi,
  type AutoJianyingDraftDownloadEntryApi,
} from '@/lib/api'
import { type Segment, type SRTEntry, audioSrc } from './_components/types'
import { ClipInOutDialog } from './_components/ClipInOutDialog'
import { buildClipTrimsForApi, computeNextTrimSlots } from './_components/clipTrim'
import { PreviewModal } from './_components/ClipCard'
import { ExportSidebar } from './_components/ExportSidebar'
import { MatchPageHeader } from './_components/MatchPageHeader'
import { VideoScopeSelector } from './_components/VideoScopeSelector'
import { ManualMatchPanel } from './_components/ManualMatchPanel'
import { AutoEditPanel } from './_components/AutoEditPanel'
import { VoiceoverQuickCutPanel, type VoiceoverQuickCutStrategy } from './_components/VoiceoverQuickCutPanel'
import { MixEditPanel, type MixEditGeneratePayload } from './_components/MixEditPanel'
import { TemplateClipPanel } from './_components/TemplateClipPanel'
import { MatchSubtitleWorkspace } from './_components/MatchSubtitleWorkspace'
import { isAutoLikeMode } from './_components/matchModeTypes'
import { type AutoPlanStage } from './_components/autoEditTypes'
import { useMatchStore } from '@/lib/store'
import { VideoResultDrawer } from '@/app/_components/VideoResultDrawer'
import { useToast } from '@/components/ui/toast-provider'
import { toastRecommendJianyingParentDir } from '@/lib/jianying-parent-dir-hint'
import { ReplicaTemplateWizard } from './_components/ReplicaTemplateWizard'
import { ReplicaTemplateLibrary } from './_components/ReplicaTemplateLibrary'
import { ScriptStockPanel } from './_components/ScriptStockPanel'
import {
  buildVoiceoverRedubPlan,
  DEFAULT_VOICEOVER_TTS_ALIGN,
  voiceoverPlanSupportsRedub,
} from '@/lib/voiceoverRedub'
import { appendIdToOrderedList, toggleIdInOrderedList } from '@/lib/match/orderedSelection'

const VIDEO_PAGE_SIZE = 9
const REPLICA_LOCKED_TEMPLATE_PRESET = 'replica_locked'

function mapReplicaTypeToPreset(replicaType: 'short_video' | 'film_commentary' | 'scene_story' | ''): string {
  if (replicaType === 'film_commentary') return 'replica_film_commentary'
  if (replicaType === 'scene_story') return 'replica_scene_story'
  if (replicaType === 'short_video') return 'replica_short_video'
  return REPLICA_LOCKED_TEMPLATE_PRESET
}

function normalizeAutoPlanStage(stage?: string): AutoPlanStage {
  if (!stage) return 'planning'
  const lower = stage.toLowerCase()
  if (lower === 'idle') return 'idle'
  if (lower === 'preparing' || lower === 'init') return 'preparing'
  if (lower === 'connecting' || lower === 'context') return 'connecting'
  if (lower === 'planning' || lower === 'llm' || lower === 'post') return 'planning'
  if (lower === 'done' || lower === 'result') return 'done'
  if (lower === 'failed' || lower === 'error') return 'failed'
  return 'planning'
}

function mapTemplatePresetToContentStyle(
  preset: string
): 'generic' | 'ecommerce' | 'voiceover' | 'commentary' {
  if (preset.includes('film') || preset.includes('scene')) return 'commentary'
  if (preset.includes('ecommerce') || preset.includes('marketing')) return 'ecommerce'
  if (preset.includes('short') || preset.includes('voiceover')) return 'voiceover'
  return 'generic'
}

function contentStyleLabel(style: 'generic' | 'ecommerce' | 'voiceover' | 'commentary'): string {
  if (style === 'ecommerce') return '电商'
  if (style === 'voiceover') return '口播'
  if (style === 'commentary') return '影视'
  return '通用'
}

function getRecommendedEventsProfile(style: 'generic' | 'ecommerce' | 'voiceover' | 'commentary') {
  if (style === 'ecommerce') {
    return { clips: 28, chars: 20000, overlap: 2, batches: 18 }
  }
  if (style === 'voiceover') {
    return { clips: 24, chars: 17000, overlap: 3, batches: 20 }
  }
  if (style === 'commentary') {
    return { clips: 20, chars: 15000, overlap: 4, batches: 24 }
  }
  return { clips: 25, chars: 18000, overlap: 2, batches: 16 }
}

export default function MatchPage() {
  const {
    segments,
    setMatchSegments,
    globalQuery,
    setMatchGlobalQuery,
    selectedVideoIds,
    setMatchSelectedVideoIds,
    topK,
    setMatchTopK,
    topN,
    setMatchTopN,
    subtitleEnabled,
    setMatchSubtitleEnabled,
    subtitleStyle,
    setMatchSubtitleStyle,
    exportMode,
    setMatchExportMode,
    matchMode: mode,
    autoTemplateEnabled,
    setAutoTemplateEnabled,
    templatePreset,
    templatePresetSource,
    setTemplatePreset,
    setTemplatePresetSource,
    setMatchMode,
    setMatchSegmentCounter,
    autoPrompt,
    setAutoPrompt,
    autoMode,
    setAutoMode,
    autoTargetDuration,
    setAutoTargetDuration,
    autoNumPlans,
    setAutoNumPlans,
    autoBgmMixEnabled,
    setAutoBgmMixEnabled,
    autoBgmPlanPolicy,
    setAutoBgmPlanPolicy,
    autoBgmTrackFilename,
    setAutoBgmTrackFilename,
    autoUseTimelineEngine,
    setAutoUseTimelineEngine,
    autoExplain,
    setAutoExplain,
    autoContentStyle,
    setAutoContentStyle,
    autoEventsAdvancedEnabled,
    setAutoEventsAdvancedEnabled,
    autoEventsMaxClipsPerBatch,
    setAutoEventsMaxClipsPerBatch,
    autoEventsMaxCharsPerBatch,
    setAutoEventsMaxCharsPerBatch,
    autoEventsBatchOverlapClips,
    setAutoEventsBatchOverlapClips,
    autoEventsMaxBatches,
    setAutoEventsMaxBatches,
    replicaTemplateGuide,
    setReplicaTemplateGuide,
    setReplicaTemplateType,
    autoPlans,
    setAutoPlans,
    autoRealizeDownloads,
    setAutoRealizeDownloads,
    autoExpandedPlanIds,
    setAutoExpandedPlanIds,
    autoPlanLogs,
    setAutoPlanLogs,
  } = useMatchStore()

  
  const toast = useToast()
  const setSelectedVideoIds = (fn: string[] | ((prev: string[]) => string[])) =>
    setMatchSelectedVideoIds(typeof fn === 'function' ? fn(useMatchStore.getState().selectedVideoIds) : fn)
  const setGlobalQuery = setMatchGlobalQuery
  const setTopK = setMatchTopK
  const setTopN = setMatchTopN
  const setSubtitleEnabled = setMatchSubtitleEnabled
  const setSubtitleStyle = setMatchSubtitleStyle
  const setExportMode = setMatchExportMode


  const [videos, setVideos] = useState<Video[]>([])
  const [videoSearch, setVideoSearch] = useState('')
  const [videoPage, setVideoPage] = useState(1)
  const [previewClip, setPreviewClip] = useState<MatchClip | null>(null)
  const [clipInOutSegId, setClipInOutSegId] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playingSegId, setPlayingSegId] = useState<string | null>(null)
  const [audioCurrentTime, setAudioCurrentTime] = useState(0)
  const [audioDuration, setAudioDuration] = useState(0)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [exportBackend, setExportBackend] = useState<'moviepy' | 'ffmpeg'>('moviepy')
  const [globalMatching, setGlobalMatching] = useState(false)
  const [globalTtsSynthesising, setGlobalTtsSynthesising] = useState(false)
  const [srtEntries, setSrtEntries] = useState<SRTEntry[]>([])
  const [timingSource, setTimingSource] = useState('')
  const [generatingSrt, setGeneratingSrt] = useState(false)
  const [srtError, setSrtError] = useState('')
  const [strictUseClientSrt, setStrictUseClientSrt] = useState(false)
  const [previewVideoSize, setPreviewVideoSize] = useState<{ width: number; height: number } | null>(null)
  const [resultOpen, setResultOpen] = useState(false)
  const [replicaTemplateRefreshSignal, setReplicaTemplateRefreshSignal] = useState(0)
  const [bgmTracks, setBgmTracks] = useState<BgmTrack[]>([])
  const [bgmListError, setBgmListError] = useState('')
  const [manualBgmEnabled, setManualBgmEnabled] = useState(false)
  const [manualBgmTrackIds, setManualBgmTrackIds] = useState<string[]>([])
  const [manualBgmVolumeByTrackId, setManualBgmVolumeByTrackId] = useState<Record<string, number>>({})
  const [manualBgmTimelineSegments, setManualBgmTimelineSegments] = useState<
    Array<{ id: string; startSec: number; endSec: number; trackId?: string; volumeDb?: number }>
  >([])
  const [voiceoverBgmEnabled, setVoiceoverBgmEnabled] = useState(false)
  const [voiceoverBgmTrackIds, setVoiceoverBgmTrackIds] = useState<string[]>([])
  const [voiceoverBgmVolumeByTrackId, setVoiceoverBgmVolumeByTrackId] = useState<Record<string, number>>({})
  const [voiceoverBgmTimelineSegments, setVoiceoverBgmTimelineSegments] = useState<
    Array<{ id: string; startSec: number; endSec: number; trackId?: string; volumeDb?: number }>
  >([])
  const [voiceoverRedubEnabled, setVoiceoverRedubEnabled] = useState(false)
  const [voiceoverTtsAlign, setVoiceoverTtsAlign] = useState<TtsVideoAlignConfigApi>(() => ({
    ...DEFAULT_VOICEOVER_TTS_ALIGN,
  }))
  const [mixEditTtsAlign, setMixEditTtsAlign] = useState<TtsVideoAlignConfigApi>(() => ({
    ...DEFAULT_VOICEOVER_TTS_ALIGN,
    policy: 'loop_video_to_cover',
  }))
  const [autoCustomBgmEnabled, setAutoCustomBgmEnabled] = useState(false)
  const [autoCustomBgmTrackIds, setAutoCustomBgmTrackIds] = useState<string[]>([])
  const [autoCustomBgmVolumeByTrackId, setAutoCustomBgmVolumeByTrackId] = useState<Record<string, number>>({})
  const [autoCustomBgmTimelineSegments, setAutoCustomBgmTimelineSegments] = useState<
    Array<{ id: string; startSec: number; endSec: number; trackId?: string; volumeDb?: number }>
  >([])

  // 自动成片 · 仅会话态（不持久化）
  const [autoLoading, setAutoLoading] = useState(false)
  const [autoError, setAutoError] = useState('')
  const [autoRealizingId, setAutoRealizingId] = useState<string | null>(null)
  const [autoJianyingDraftExportingId, setAutoJianyingDraftExportingId] = useState<string | null>(null)
  const [autoJianyingDraftDownloads, setAutoJianyingDraftDownloads] = useState<
    Record<string, AutoJianyingDraftDownloadEntryApi>
  >({})
  const [autoRealizeMsg, setAutoRealizeMsg] = useState('')
  const [autoPlanStartedAt, setAutoPlanStartedAt] = useState<number | null>(null)
  const [autoPlanElapsedSec, setAutoPlanElapsedSec] = useState(0)

  // 与系统设置保持一致：导出默认后端由 /api/config 控制
  useEffect(() => {
    apiClient
      .get<unknown, Record<string, { value?: string }>>('/api/config')
      .then((cfg) => {
        const v = String(cfg?.export_backend?.value ?? '').trim().toLowerCase()
        if (v === 'ffmpeg' || v === 'moviepy') setExportBackend(v)
      })
      .catch(() => {
        // 忽略：保持默认 moviepy
      })
  }, [])

  const showStrictSrtToggle =
    (exportMode === 'subtitle' || exportMode === 'jianying_tts') && subtitleEnabled
  useEffect(() => {
    if (!showStrictSrtToggle && strictUseClientSrt) setStrictUseClientSrt(false)
  }, [showStrictSrtToggle, strictUseClientSrt])
  const [autoPlanStage, setAutoPlanStage] = useState<AutoPlanStage>('idle')

  const autoPlanStagePercent: Record<AutoPlanStage, number> = {
    idle: 0,
    preparing: 10,
    connecting: 25,
    planning: 70,
    done: 100,
    failed: 100,
  }

  function appendAutoPlanLog(message: string) {
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    setAutoPlanLogs((prev) => [...prev, `${time} ${message}`])
  }

  /** 复刻模板确认后：跳转到「手动匹配」流水线（注入 store，供文案生成使用） */
  function goReplicaToManualPipeline() {
    const g = useMatchStore.getState().replicaTemplateGuide.trim()
    if (!g) {
      toast.error('请先在上方生成并确认复刻模板，或从模板库选用')
      return
    }
    setMatchMode('manual')
    toast.success('已切换至「手动匹配」：复刻约束将用于 AI 文案生成')
  }

  /** 复刻模板确认后：跳转到「一键成片」流水线（将约束写入剪辑诉求） */
  function goReplicaToAutoPipeline() {
    const g = useMatchStore.getState().replicaTemplateGuide.trim()
    if (!g) {
      toast.error('请先在上方生成并确认复刻模板，或从模板库选用')
      return
    }
    setAutoPrompt(`【复刻模板约束】\n${g}\n\n【用户诉求】\n`)
    setTemplatePreset(mapReplicaTypeToPreset(useMatchStore.getState().replicaTemplateType))
    setTemplatePresetSource('replica')
    setMatchMode('auto')
    window.scrollTo({ top: 0, behavior: 'auto' })
    toast.success('已切换至「一键成片」：请在剪辑诉求中补充主题后生成方案')
  }

  useEffect(() => {
    if (!autoLoading || autoPlanStartedAt === null) return
    setAutoPlanElapsedSec(Math.max(0, Math.floor((Date.now() - autoPlanStartedAt) / 1000)))
    const timer = window.setInterval(() => {
      setAutoPlanElapsedSec(Math.max(0, Math.floor((Date.now() - autoPlanStartedAt) / 1000)))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [autoLoading, autoPlanStartedAt])

  useEffect(() => {
    const loadAllVideos = async () => {
      try {
        const first = await apiClient.get<unknown, {
          items?: Video[]
          total_pages?: number
          page?: number
          page_size?: number
        } | Video[]>('/api/videos')
        if (Array.isArray(first)) {
          setVideos(first)
          return
        }
        const firstItems = first?.items || []
        const totalPages = Number(first?.total_pages || 1)
        const currentPage = Number(first?.page || 1)
        const pageSize = Number(first?.page_size || firstItems.length || 12)
        if (totalPages <= currentPage) {
          setVideos(firstItems)
          return
        }
        const restPages = await Promise.all(
          Array.from({ length: totalPages - currentPage }, (_, i) => currentPage + i + 1).map((p) =>
            apiClient.get<unknown, { items?: Video[] }>('/api/videos', {
              params: { page: p, page_size: pageSize },
            }),
          ),
        )
        setVideos([
          ...firstItems,
          ...restPages.flatMap((res) => res?.items || []),
        ])
      } catch (e) {
        console.error(e)
      }
    }
    void loadAllVideos()
  }, [])

  useEffect(() => {
    bgmApi.list()
      .then((list) => {
        setBgmTracks(Array.isArray(list) ? list : [])
        setBgmListError('')
      })
      .catch((e: unknown) => {
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'BGM 列表加载失败'
        setBgmTracks([])
        setBgmListError(msg)
      })
  }, [])

  // 兼容旧的 matchMode=template：一旦进入模板模式，默认打开模板开关
  useEffect(() => {
    if (mode === 'template') {
      setAutoTemplateEnabled(true)
      setMatchMode('auto')
    }
  }, [mode, setAutoTemplateEnabled, setMatchMode])

  const doneVideos = useMemo(
    () => videos.filter((v) => v.status === 'done' && v.total_clips > 0),
    [videos]
  )
  const voiceoverScopeVideos = useMemo(
    () => videos.filter((v) => v.status !== 'error'),
    [videos]
  )
  const scopeVideos =
    mode === 'voiceover' || mode === 'script_stock' || mode === 'mix_edit'
      ? voiceoverScopeVideos
      : doneVideos
  const selectedOrAllDoneVideos = useMemo(
    () =>
      selectedVideoIds.length > 0
        ? scopeVideos.filter((v) => selectedVideoIds.includes(v.id))
        : scopeVideos,
    [scopeVideos, selectedVideoIds]
  )
  const estimatedTotalClips = useMemo(
    () => selectedOrAllDoneVideos.reduce((sum, v) => sum + Number(v.total_clips || 0), 0),
    [selectedOrAllDoneVideos]
  )
  const templateModeEnabled = mode === 'template' || autoTemplateEnabled
  const effectiveContentStyle = templateModeEnabled
    ? mapTemplatePresetToContentStyle(templatePreset || '')
    : autoContentStyle
  const recommendedProfile = getRecommendedEventsProfile(effectiveContentStyle)
  const effectiveEventsMaxClipsPerBatch =
    autoEventsAdvancedEnabled && typeof autoEventsMaxClipsPerBatch === 'number'
      ? Math.max(5, autoEventsMaxClipsPerBatch)
      : recommendedProfile.clips
  const effectiveEventsMaxBatches =
    autoEventsAdvancedEnabled && typeof autoEventsMaxBatches === 'number'
      ? Math.max(1, autoEventsMaxBatches)
      : recommendedProfile.batches
  const estimatedBatches = Math.min(
    effectiveEventsMaxBatches,
    Math.max(1, Math.ceil(Math.max(1, estimatedTotalClips) / Math.max(5, effectiveEventsMaxClipsPerBatch)))
  )
  const estimatedSeconds = Math.max(20, 10 + estimatedBatches * 18)

  useEffect(() => {
    const valid = new Set(scopeVideos.map((v) => v.id))
    const prev = useMatchStore.getState().selectedVideoIds
    const next = prev.filter((id) => valid.has(id))
    if (next.length !== prev.length) {
      setMatchSelectedVideoIds(next)
    }
  }, [scopeVideos, setMatchSelectedVideoIds])
  const filteredScopeVideos = useMemo(() => {
    const q = videoSearch.trim().toLowerCase()
    return q ? scopeVideos.filter((v) => v.name.toLowerCase().includes(q)) : scopeVideos
  }, [scopeVideos, videoSearch])
  const effectiveCopyGenVideoIds = useMemo(
    () => (selectedVideoIds.length > 0 ? selectedVideoIds : doneVideos.map((v) => v.id)),
    [selectedVideoIds, doneVideos]
  )
  const videoTotalPages = Math.max(1, Math.ceil(filteredScopeVideos.length / VIDEO_PAGE_SIZE))
  const pagedScopeVideos = filteredScopeVideos.slice((videoPage - 1) * VIDEO_PAGE_SIZE, videoPage * VIDEO_PAGE_SIZE)
  const handleVideoSearch = (val: string) => { setVideoSearch(val); setVideoPage(1) }

  function makeSeg(id: string, text = ''): Segment {
    return {
      id, text, clips: [], chosenIdx: 0, selectedClipIds: [], clipTrimByClipId: {}, clipTrimSlots: undefined,
      ttsFilename: null, ttsLoading: false, ttsError: '', matchLoading: false, matchError: '', expanded: false,
    }
  }
  function patchSeg(id: string, p: Partial<Segment>) {
    setMatchSegments(useMatchStore.getState().segments.map((s) => s.id === id ? { ...s, ...p } : s))
  }
  function addSegment(text = '') {
    const c = useMatchStore.getState().segmentCounter
    const id = `seg-${c}`
    setMatchSegmentCounter(c + 1)
    setMatchSegments([...useMatchStore.getState().segments, makeSeg(id, text)])
  }
  function removeSegment(id: string) { setMatchSegments(useMatchStore.getState().segments.filter((s) => s.id !== id)) }

  function moveSegment(fromId: string, toId: string) {
    if (fromId === toId) return
    const list = [...useMatchStore.getState().segments]
    const from = list.findIndex((s) => s.id === fromId)
    const to = list.findIndex((s) => s.id === toId)
    if (from < 0 || to < 0) return
    const [item] = list.splice(from, 1)
    list.splice(to, 0, item)
    setMatchSegments(list)
  }

  function moveSegmentRel(segId: string, action: 'up' | 'down' | 'top' | 'bottom') {
    const list = [...useMatchStore.getState().segments]
    const from = list.findIndex((s) => s.id === segId)
    if (from < 0) return
    let to = from
    if (action === 'up') to = Math.max(0, from - 1)
    else if (action === 'down') to = Math.min(list.length - 1, from + 1)
    else if (action === 'top') to = 0
    else if (action === 'bottom') to = list.length - 1
    if (to === from) return
    const [item] = list.splice(from, 1)
    list.splice(to, 0, item)
    setMatchSegments(list)
  }

  function splitGlobalQuery() {
    if (!globalQuery.trim()) return
    let parts = globalQuery.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)
    if (parts.length <= 1) parts = globalQuery.split(/(?<=[。！？!?])\s*/).map((p) => p.trim()).filter(Boolean)
    if (parts.length <= 1) parts = globalQuery.split(/\n/).map((p) => p.trim()).filter(Boolean)
    if (!parts.length) return
    const c = useMatchStore.getState().segmentCounter
    setMatchSegments(parts.map((t, i) => makeSeg(`seg-${c + i}`, t)))
    setMatchSegmentCounter(c + parts.length)
  }
  function handleAiApply(parts: string[]) {
    if (!parts.length) return
    setGlobalQuery(parts.join('\n\n'))
    const c = useMatchStore.getState().segmentCounter
    setMatchSegments(parts.map((t, i) => makeSeg(`seg-${c + i}`, t)))
    setMatchSegmentCounter(c + parts.length)
  }

  async function matchSegment(id: string) {
    const seg = useMatchStore.getState().segments.find((s) => s.id === id)
    if (!seg || !seg.text.trim()) return
    patchSeg(id, { matchLoading: true, matchError: '' })
    try {
      const data = await apiClient.post<unknown, { recommended: MatchClip[]; candidates: MatchClip[] }>('/api/match', {
        query: seg.text.trim(), top_k: topK, top_n: topN,
        video_ids: selectedVideoIds.length > 0 ? selectedVideoIds : null,
      })
      const clips = data.recommended?.length ? data.recommended : data.candidates
      // 匹配后默认把最高分 clip 设为唯一选中（保留用户之前手动勾选的逻辑由 toggleClipSelected 管理）
      const defaultSelected = clips.length > 0 ? [clips[0].clip_id] : []
      patchSeg(id, {
        clips,
        chosenIdx: 0,
        selectedClipIds: defaultSelected,
        matchLoading: false,
        clipTrimSlots: undefined,
      })
    } catch (e: unknown) {
      patchSeg(id, { matchLoading: false, matchError: (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '匹配失败' })
    }
  }
  async function matchAll() { setGlobalMatching(true); await Promise.all(segments.map((s) => matchSegment(s.id))); setGlobalMatching(false) }

  async function synthesiseTts(id: string) {
    const seg = useMatchStore.getState().segments.find((s) => s.id === id)
    if (!seg || !seg.text.trim()) return
    patchSeg(id, { ttsLoading: true, ttsError: '' })
    try {
      const res = await ttsApi.synthesize({ text: seg.text.trim() })
      patchSeg(id, { ttsLoading: false, ttsFilename: res.filename })
    } catch (e: unknown) {
      patchSeg(id, { ttsLoading: false, ttsError: (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'TTS失败' })
    }
  }

  async function synthesiseAllTts() {
    const ids = useMatchStore.getState().segments.filter((s) => s.text.trim()).map((s) => s.id)
    if (!ids.length) return
    setGlobalTtsSynthesising(true)
    try {
      for (const id of ids) {
        await synthesiseTts(id)
      }
    } finally {
      setGlobalTtsSynthesising(false)
    }
  }

  function playAudio(segId: string, filename: string) {
    audioRef.current?.pause()
    const audio = new Audio(audioSrc(filename))
    audioRef.current = audio
    setPlayingSegId(segId)
    setAudioCurrentTime(0)
    setAudioDuration(0)

    audio.preload = 'metadata'
    audio.onloadedmetadata = () => setAudioDuration(Number.isFinite(audio.duration) ? audio.duration : 0)
    audio.ontimeupdate = () => setAudioCurrentTime(audio.currentTime || 0)
    audio.onended = () => { setPlayingSegId(null); setAudioCurrentTime(0) }
    audio.onerror = () => { setPlayingSegId(null); setAudioCurrentTime(0); setAudioDuration(0) }
    audio.play()
  }
  function stopAudio() {
    audioRef.current?.pause()
    audioRef.current = null
    setPlayingSegId(null)
    setAudioCurrentTime(0)
    setAudioDuration(0)
  }

  function seekAudio(t: number) {
    const a = audioRef.current
    if (!a) return
    const next = Math.max(0, Math.min(Number.isFinite(a.duration) ? a.duration : audioDuration, t))
    a.currentTime = next
    setAudioCurrentTime(next)
  }

  // 注：历史实现曾把候选 clips 全部拼进 clip_ids，导致导出混入“未选素材”。
  // 现在一键成片/字幕烧录只使用 selectedClipIds（见 handleExport 内 exportMode==='subtitle' 分支）。

  const readySegs = segments.filter((s) => s.clips.length > 0)

  const clipInOutSeg = useMemo(() => {
    if (!clipInOutSegId) return undefined
    return segments.find((s) => s.id === clipInOutSegId)
  }, [clipInOutSegId, segments])

  useEffect(() => {
    if (!clipInOutSegId) return
    const s = segments.find((x) => x.id === clipInOutSegId)
    if (!s || (s.selectedClipIds?.length ?? 0) === 0) setClipInOutSegId(null)
  }, [segments, clipInOutSegId])

  const firstReadyClipId = useMemo(() => {
    const first = segments.find((s) => s.clips.length > 0)
    if (!first) return ''
    return first.clips[first.chosenIdx]?.clip_id ?? ''
  }, [segments])
  const subtitlePreviewFrameUrl = useMemo(() => {
    for (const seg of segments) {
      if (!seg.clips.length) continue
      const primaryClipId = seg.selectedClipIds?.[0] ?? seg.clips[seg.chosenIdx]?.clip_id ?? ''
      const primaryClip = seg.clips.find((clip) => clip.clip_id === primaryClipId)
      if (primaryClip?.thumbnail_url) return primaryClip.thumbnail_url
      const fallback = seg.clips.find((clip) => clip.thumbnail_url)
      if (fallback?.thumbnail_url) return fallback.thumbnail_url
    }
    return null
  }, [segments])

  useEffect(() => {
    if (!firstReadyClipId) {
      setPreviewVideoSize(null)
      return
    }

    const video = document.createElement('video')
    video.preload = 'metadata'
    video.src = `${API_BASE_URL}/api/videos/clips/${firstReadyClipId}/stream`
    video.onloadedmetadata = () => {
      if (video.videoWidth > 0 && video.videoHeight > 0) {
        setPreviewVideoSize({ width: video.videoWidth, height: video.videoHeight })
      }
    }
    video.onerror = () => setPreviewVideoSize(null)
  }, [firstReadyClipId])

  async function generateSrt(): Promise<string> {
    setGeneratingSrt(true); setSrtError('')
    try {
      const segsInput = readySegs
        .map((s) => {
          const clip_id = (s.selectedClipIds?.[0] ?? s.clips[s.chosenIdx]?.clip_id) ?? ''
          const clip_ids = (s.selectedClipIds?.length ? s.selectedClipIds : [clip_id]).filter(Boolean) as string[]
          const clip_trims = buildClipTrimsForApi(s, clip_ids)
          return {
            copy_text: s.text,
            clip_id,
            clip_ids: clip_ids.length > 1 ? clip_ids : undefined,
            tts_filename: s.ttsFilename ?? undefined,
            ...(clip_trims.length ? { clip_trims } : {}),
          }
        })
        .filter((s) => s.clip_id)
      const res = await subtitleApi.generate({ segments: segsInput, style: subtitleStyle, use_tts_timing: true })
      setSrtEntries(res.entries); setTimingSource(res.timing_source)
      return res.srt_content
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'SRT生成失败'
      setSrtError(msg); throw new Error(msg)
    } finally { setGeneratingSrt(false) }
  }

  async function handleExport() {
    if (exporting) return
    const projectName = globalQuery.slice(0, 30).replace(/\s+/g, '_') || 'smartclip_project'
    try {
      // 一键成片 / 剪映 TTS 草稿：先在前端拦截未完成配音，避免后端因缺音频报错
      if (exportMode === 'subtitle' || exportMode === 'jianying_tts') {
        const needTtsSegs = readySegs
        const missingTtsSegs = needTtsSegs.filter((s) => !s.ttsFilename)
        const loadingTtsSegs = needTtsSegs.filter((s) => !s.ttsFilename && s.ttsLoading)
        const failedTtsSegs = needTtsSegs.filter((s) => !s.ttsFilename && !!s.ttsError)

        if (missingTtsSegs.length > 0) {
          const tip =
            loadingTtsSegs.length > 0
              ? `还有 ${missingTtsSegs.length} 段配音未就绪（${loadingTtsSegs.length} 段合成中），请等待配音完成后再导出。`
              : failedTtsSegs.length > 0
                ? `还有 ${missingTtsSegs.length} 段配音未就绪（${failedTtsSegs.length} 段合成失败），请先重新合成配音后再导出。`
                : `还有 ${missingTtsSegs.length} 段未生成配音，请先完成配音合成后再导出。`
          toast.info(tip)
          return
        }
      }

      setExporting(true); setExportError('')
      if (exportMode === 'zip') {
        const clipIds = readySegs
          .map((s) => (s.selectedClipIds?.[0] ?? s.clips[s.chosenIdx]?.clip_id))
          .filter(Boolean) as string[]
        const blob = await exportApi.downloadProject({ clip_ids: clipIds, project_name: projectName, include_audio: true, tts_filenames: readySegs.map((s) => s.ttsFilename ?? '') })
        triggerDownload(blob as unknown as Blob, `${projectName}.zip`)
      } else if (exportMode === 'subtitle') {
        if (readySegs.length === 0) return
        const currentSrt = subtitleEnabled ? await generateSrt() : ''
        const segsInput = readySegs
          .map((s) => {
            // 一键成片（TTS+字幕）必须严格使用“用户勾选的素材”顺序，不能把候选列表混入导出。
            const cid = (s.selectedClipIds?.[0] ?? s.clips[s.chosenIdx]?.clip_id) ?? ''
            const clip_ids = (s.selectedClipIds?.length ? s.selectedClipIds : [cid]).filter(Boolean) as string[]
            const clip_trims = buildClipTrimsForApi(s, clip_ids)
            return {
              copy_text: s.text,
              clip_id: cid,
              clip_ids: clip_ids.length > 1 ? clip_ids : undefined,
              tts_filename: s.ttsFilename ?? undefined,
              ...(clip_trims.length ? { clip_trims } : {}),
            }
          })
          .filter((s) => s.clip_id)
        const res = await subtitleApi.burn({
          segments: segsInput,
          srt_content: currentSrt,
          style: subtitleStyle,
          project_name: projectName,
          export_backend: exportBackend,
          strict_use_client_srt: strictUseClientSrt,
          bgm: buildManualBgmPayload(),
        })
        const downloadUrl = `${API_BASE_URL}/api/subtitle/download/${res.filename}`
        const a = document.createElement('a')
        a.href = downloadUrl
        a.download = res.filename
        a.click()
      } else if (exportMode === 'jianying_tts') {
        if (readySegs.length === 0) return
        const currentSrt = subtitleEnabled ? await generateSrt() : ''
        const segsInput = readySegs
          .map((s) => {
            const cid = (s.selectedClipIds?.[0] ?? s.clips[s.chosenIdx]?.clip_id) ?? ''
            const clip_ids = (s.selectedClipIds?.length ? s.selectedClipIds : [cid]).filter(Boolean) as string[]
            const clip_trims = buildClipTrimsForApi(s, clip_ids)
            return {
              copy_text: s.text,
              clip_id: cid,
              clip_ids: clip_ids.length > 1 ? clip_ids : undefined,
              tts_filename: s.ttsFilename ?? undefined,
              ...(clip_trims.length ? { clip_trims } : {}),
            }
          })
          .filter((s) => s.clip_id)
        const res = await subtitleApi.exportJianyingDraft({
          mode: 'tts',
          segments: segsInput,
          srt_content: currentSrt,
          style: subtitleStyle,
          project_name: projectName,
          strict_use_client_srt: strictUseClientSrt,
        })
        if (res.mode === 'direct' && res.local_path) {
          toast.success(`剪映草稿已写入：${res.local_path}`)
          return
        }
        const a = document.createElement('a')
        a.href = res.url
        a.download = res.filename
        a.click()
        toastRecommendJianyingParentDir(toast)
      } else if (exportMode === 'original') {
        const exportSegs = segments.filter((s) => (s.selectedClipIds?.length ?? 0) > 0)
        if (exportSegs.length === 0) return
        const segsInput = exportSegs
          .map((s) => {
            const clip_ids = s.selectedClipIds
            const cid = clip_ids[0] ?? ''
            const clip_trims = buildClipTrimsForApi(s, clip_ids)
            return {
              copy_text: s.text,
              clip_id: cid,
              clip_ids,
              tts_filename: undefined,
              ...(clip_trims.length ? { clip_trims } : {}),
            }
          })
          .filter((s) => s.clip_id)
        const res = await subtitleApi.exportOriginal({
          segments: segsInput,
          style: subtitleStyle,
          project_name: projectName,
          include_subtitle: subtitleEnabled,
          normalize_audio: true,
          export_backend: exportBackend,
          bgm: buildManualBgmPayload(),
        })
        const downloadUrl = `${API_BASE_URL}/api/subtitle/download/${res.filename}`
        const a = document.createElement('a')
        a.href = downloadUrl
        a.download = res.filename
        a.click()
      } else if (exportMode === 'jianying_original') {
        const exportSegs = segments.filter((s) => (s.selectedClipIds?.length ?? 0) > 0)
        if (exportSegs.length === 0) return
        const segsInput = exportSegs
          .map((s) => {
            const clip_ids = s.selectedClipIds
            const cid = clip_ids[0] ?? ''
            const clip_trims = buildClipTrimsForApi(s, clip_ids)
            return {
              copy_text: s.text,
              clip_id: cid,
              clip_ids,
              tts_filename: undefined,
              ...(clip_trims.length ? { clip_trims } : {}),
            }
          })
          .filter((s) => s.clip_id)
        const res = await subtitleApi.exportJianyingDraft({
          mode: 'original',
          segments: segsInput,
          style: subtitleStyle,
          project_name: projectName,
          include_subtitle: subtitleEnabled,
        })
        if (res.mode === 'direct' && res.local_path) {
          toast.success(`剪映草稿已写入：${res.local_path}`)
          return
        }
        const a = document.createElement('a')
        a.href = res.url
        a.download = res.filename
        a.click()
        toastRecommendJianyingParentDir(toast)
      }
    } catch (e: unknown) {
      setExportError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (e as Error).message || '导出失败')
    } finally { setExporting(false) }
  }

  function triggerDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 500)
  }
  const toggleVideo = (id: string) =>
    setSelectedVideoIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])

  const buildManualBgmPayload = () => {
    if (!manualBgmEnabled || manualBgmTrackIds.length === 0) return undefined
    const timeline_segments = manualBgmTimelineSegments
      .map((seg) => ({
        start_sec: Math.max(0, Number(seg.startSec) || 0),
        end_sec: Math.max(0, Number(seg.endSec) || 0),
        track_id: seg.trackId || undefined,
        volume_db: typeof seg.volumeDb === 'number' && Number.isFinite(seg.volumeDb) ? seg.volumeDb : undefined,
      }))
      .filter((seg) => seg.end_sec > seg.start_sec)
    return {
      enabled: true,
      track_ids: manualBgmTrackIds,
      track_id: manualBgmTrackIds[0],
      track_volumes_db: manualBgmVolumeByTrackId,
      volume_db: -14,
      loop: true,
      fade_in_sec: 0.5,
      fade_out_sec: 0.8,
      timeline_segments: timeline_segments.length ? timeline_segments : undefined,
    }
  }

  const buildVoiceoverBgmPlanPayload = (): AutoEditBgmPlanApi | null => {
    if (!voiceoverBgmEnabled || voiceoverBgmTrackIds.length === 0) return null
    const timeline_segments = voiceoverBgmTimelineSegments
      .map((seg) => ({
        start_sec: Math.max(0, Number(seg.startSec) || 0),
        end_sec: Math.max(0, Number(seg.endSec) || 0),
        track_id: seg.trackId || undefined,
        volume_db: typeof seg.volumeDb === 'number' && Number.isFinite(seg.volumeDb) ? seg.volumeDb : undefined,
      }))
      .filter((seg) => seg.end_sec > seg.start_sec)
    return {
      enabled: true,
      source: 'user',
      track_id: voiceoverBgmTrackIds[0],
      track_ids: voiceoverBgmTrackIds,
      track_volumes_db: voiceoverBgmVolumeByTrackId,
      volume_db: -14,
      loop: true,
      fade_in_sec: 0.5,
      fade_out_sec: 0.8,
      timeline_segments: timeline_segments.length ? timeline_segments : undefined,
    }
  }
  const buildAutoCustomBgmPlanPayload = (): AutoEditBgmPlanApi | null => {
    if (!autoCustomBgmEnabled || autoCustomBgmTrackIds.length === 0) return null
    const timeline_segments = autoCustomBgmTimelineSegments
      .map((seg) => ({
        start_sec: Math.max(0, Number(seg.startSec) || 0),
        end_sec: Math.max(0, Number(seg.endSec) || 0),
        track_id: seg.trackId || undefined,
        volume_db: typeof seg.volumeDb === 'number' && Number.isFinite(seg.volumeDb) ? seg.volumeDb : undefined,
      }))
      .filter((seg) => seg.end_sec > seg.start_sec)
    return {
      enabled: true,
      source: 'user',
      track_id: autoCustomBgmTrackIds[0],
      track_ids: autoCustomBgmTrackIds,
      track_volumes_db: autoCustomBgmVolumeByTrackId,
      volume_db: -14,
      loop: true,
      fade_in_sec: 0.5,
      fade_out_sec: 0.8,
      timeline_segments: timeline_segments.length ? timeline_segments : undefined,
    }
  }
  const showVoiceoverBgmConfig =
    autoBgmMixEnabled && (autoBgmPlanPolicy === 'user' || (autoBgmTrackFilename || '').trim().length > 0)
  const showAutoCustomBgmConfig =
    autoBgmMixEnabled && (autoBgmPlanPolicy === 'user' || (autoBgmTrackFilename || '').trim().length > 0)

  function toggleClipSelected(segId: string, clipId: string, e: MouseEvent) {
    const seg = useMatchStore.getState().segments.find((s) => s.id === segId)
    if (!seg) return

    const prev = seg.selectedClipIds ?? []
    const next = e.shiftKey ? appendIdToOrderedList(prev, clipId) : toggleIdInOrderedList(prev, clipId)
    const primaryId = next[0] ?? ''
    const nextChosenIdx = primaryId ? Math.max(0, seg.clips.findIndex((c) => c.clip_id === primaryId)) : 0
    const nextSlots = computeNextTrimSlots(seg, prev, seg.clipTrimSlots, next)
    patchSeg(segId, {
      selectedClipIds: next,
      clipTrimSlots: nextSlots,
      chosenIdx: nextChosenIdx,
    })
  }

  function toggleAutoExpandedPlan(planId: string) {
    setAutoExpandedPlanIds((prev) =>
      prev.includes(planId) ? prev.filter((id) => id !== planId) : [...prev, planId]
    )
  }

  function applyAutoBgmRealizeOptions(plan: AutoEditPlanApi): AutoEditPlanApi {
    const pb = plan.bgm
    const baseBgm = (): AutoEditBgmPlanApi => ({
      enabled: false,
      source: pb?.source ?? 'library',
      track_id: pb?.track_id ?? null,
      volume_db: pb?.volume_db ?? -12,
      loop: pb?.loop ?? true,
      fade_in_sec: pb?.fade_in_sec ?? 0.8,
      fade_out_sec: pb?.fade_out_sec ?? 1.0,
    })
    // 口播/混剪专用 BGM 已写入 plan 时，勿被「成片混音」总开关关掉
    if (
      pb?.enabled &&
      ((pb.track_ids?.length ?? 0) > 0 || (pb.track_id && String(pb.track_id).trim()))
    ) {
      return plan
    }
    if (!autoBgmMixEnabled) {
      return { ...plan, bgm: { ...baseBgm(), enabled: false } }
    }
    const custom = buildAutoCustomBgmPlanPayload()
    if (custom) {
      return { ...plan, bgm: custom }
    }
    const pick = (autoBgmTrackFilename || '').trim()
    if (pick) {
      return {
        ...plan,
        bgm: {
          ...baseBgm(),
          enabled: true,
          source: 'user',
          track_id: pick,
        },
      }
    }
    return {
      ...plan,
      bgm: {
        enabled: true,
        source: pb?.source ?? 'library',
        track_id: pb?.track_id ?? null,
        volume_db: pb?.volume_db ?? -12,
        loop: pb?.loop ?? true,
        fade_in_sec: pb?.fade_in_sec ?? 0.8,
        fade_out_sec: pb?.fade_out_sec ?? 1.0,
      },
    }
  }

  async function handleGenerateAutoPlans() {
    const rawUserPrompt = autoPrompt.trim()
    if (!rawUserPrompt) return
    if (selectedVideoIds.length === 0 && doneVideos.length === 0) return
    setAutoLoading(true)
    setAutoError('')
    const startedAt = Date.now()
    setAutoPlanStartedAt(startedAt)
    setAutoPlanElapsedSec(0)
    setAutoPlanLogs([])
    setAutoPlanStage('preparing')
    appendAutoPlanLog('已开始生成方案')
    appendAutoPlanLog('正在创建 SSE 规划会话...')
    try {
      appendAutoPlanLog(
        `本次配置：${templateModeEnabled ? `模板=${templatePreset || '未选'}` : '自由剪辑'}；处理档位=${contentStyleLabel(
          effectiveContentStyle
        )}${templateModeEnabled ? '（模板自动映射）' : '（手动）'}；高级覆盖=${autoEventsAdvancedEnabled ? '开启' : '关闭'}`
      )
      const payload = {
        video_ids: selectedVideoIds.length > 0 ? selectedVideoIds : doneVideos.map((v) => v.id),
        user_prompt: rawUserPrompt,
        mode: autoMode,
        template_preset: templateModeEnabled ? templatePreset : undefined,
        target_duration_sec: typeof autoTargetDuration === 'number' ? autoTargetDuration : undefined,
        num_plans: autoNumPlans,
        allow_cross_video: true,
        subtitle_policy: subtitleEnabled ? 'auto' as const : 'none' as const,
        transition_policy: 'auto' as const,
        bgm_policy: autoBgmPlanPolicy,
        use_timeline_engine: autoUseTimelineEngine,
        explain: autoUseTimelineEngine ? autoExplain : false,
        content_style: autoUseTimelineEngine ? effectiveContentStyle : undefined,
        events_max_clips_per_batch:
          autoUseTimelineEngine && autoEventsAdvancedEnabled && typeof autoEventsMaxClipsPerBatch === 'number'
            ? autoEventsMaxClipsPerBatch
            : undefined,
        events_max_chars_per_batch:
          autoUseTimelineEngine && autoEventsAdvancedEnabled && typeof autoEventsMaxCharsPerBatch === 'number'
            ? autoEventsMaxCharsPerBatch
            : undefined,
        events_batch_overlap_clips:
          autoUseTimelineEngine && autoEventsAdvancedEnabled && typeof autoEventsBatchOverlapClips === 'number'
            ? autoEventsBatchOverlapClips
            : undefined,
        events_max_batches:
          autoUseTimelineEngine && autoEventsAdvancedEnabled && typeof autoEventsMaxBatches === 'number'
            ? autoEventsMaxBatches
            : undefined,
      }
      const session = await autoEditApi.createPlanSession(payload)
      setAutoPlanStage('connecting')
      appendAutoPlanLog('会话已创建，正在连接实时流...')

      await new Promise<void>((resolve, reject) => {
        const streamUrl = `${API_BASE_URL}${session.stream_url}`
        const es = new EventSource(streamUrl)
        let finished = false

        const closeStream = () => {
          es.close()
        }

        es.addEventListener('progress', (ev) => {
          try {
            const data = JSON.parse((ev as MessageEvent).data || '{}') as { stage?: string; message?: string }
            setAutoPlanStage(normalizeAutoPlanStage(data.stage))
            appendAutoPlanLog(data.message || '收到进度更新')
          } catch {
            setAutoPlanStage('planning')
            appendAutoPlanLog('收到进度更新')
          }
        })

        es.addEventListener('result', (ev) => {
          try {
            const data = JSON.parse((ev as MessageEvent).data || '{}') as { plans?: AutoEditPlanApi[] }
            const plans = data.plans || []
            // 让候选卡片展示的 BGM 与「一键成片 realize」时一致
            setAutoPlans(plans.map((p) => applyAutoBgmRealizeOptions(p)))
            setAutoPlanStage('done')
            appendAutoPlanLog(`生成完成，返回 ${plans.length} 个方案`)
            finished = true
            closeStream()
            resolve()
          } catch {
            setAutoPlanStage('failed')
            finished = true
            closeStream()
            reject(new Error('解析实时结果失败'))
          }
        })

        es.addEventListener('failed', (ev) => {
          let msg = '生成方案失败'
          try {
            const data = JSON.parse((ev as MessageEvent).data || '{}') as { message?: string }
            msg = data.message || msg
          } catch {
            // ignore parse error
          }
          setAutoPlanStage('failed')
          finished = true
          closeStream()
          reject(new Error(msg))
        })

        es.onerror = () => {
          if (finished) return
          if (es.readyState === EventSource.CLOSED) {
            setAutoPlanStage('failed')
            closeStream()
            reject(new Error('实时连接中断，请重试'))
            return
          }
          appendAutoPlanLog('连接波动，正在自动重连...')
        }
      })
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e as Error)?.message
        || '生成方案失败'
      setAutoError(msg)
      setAutoPlanStage('failed')
      appendAutoPlanLog(`生成失败：${msg}`)
    } finally {
      setAutoLoading(false)
      setAutoPlanStartedAt(null)
    }
  }

  async function handleVoiceoverQuickCut(payload: {
    videoIds: string[]
    strategy: VoiceoverQuickCutStrategy
    userPrompt?: string
    /** 秒；仅智能快剪生效；可与提示词内「2分钟」等同时存在，显式值优先 */
    targetDurationSec?: number
    allowOverlappingSourceTimeline?: boolean
    audioActivityConfig?: {
      activityDbThreshold: number
      activityMinSilenceSec: number
      activityMinKeepSec: number
      activityMergeGapSec: number
      activityHeadPadSec: number
      activityTailPadSec: number
      activityKeepRanges?: Array<{ video_id: string; start: number; end: number }>
    }
  }) {
    setAutoError('')
    setAutoLoading(true)
    try {
      const res = await autoEditApi.voiceoverQuickCut({
        video_ids: payload.videoIds,
        strategy: payload.strategy,
        user_prompt: payload.userPrompt,
        target_duration_sec:
          typeof payload.targetDurationSec === 'number' && Number.isFinite(payload.targetDurationSec)
            ? payload.targetDurationSec
            : undefined,
        allow_overlapping_source_timeline: Boolean(payload.allowOverlappingSourceTimeline),
        activity_db_threshold: payload.audioActivityConfig?.activityDbThreshold,
        activity_min_silence_sec: payload.audioActivityConfig?.activityMinSilenceSec,
        activity_min_keep_sec: payload.audioActivityConfig?.activityMinKeepSec,
        activity_merge_gap_sec: payload.audioActivityConfig?.activityMergeGapSec,
        activity_head_pad_sec: payload.audioActivityConfig?.activityHeadPadSec,
        activity_tail_pad_sec: payload.audioActivityConfig?.activityTailPadSec,
        activity_keep_ranges: payload.audioActivityConfig?.activityKeepRanges,
      })
      const plans = res.plans || []
      setAutoPlans(plans.map((p) => applyAutoBgmRealizeOptions(p)))
      toast.success(plans.length ? `快剪方案已生成（${plans.length} 个）` : '快剪方案已生成')
    } catch (e: unknown) {
      const raw = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      let msg: string
      if (typeof raw === 'string') {
        msg = raw
      } else if (raw && typeof raw === 'object' && 'message' in (raw as object)) {
        msg = String((raw as { message: unknown }).message)
      } else {
        msg = (e as Error)?.message || '快剪方案生成失败'
      }
      setAutoError(msg)
    } finally {
      setAutoLoading(false)
    }
  }

  async function handleMixEditPlan(payload: MixEditGeneratePayload) {
    setAutoError('')
    setAutoLoading(true)
    try {
      const useTtsTrack =
        payload.mixAudioMode === 'mute_all_original' &&
        (payload.muteAudioTrack === 'ai_tts_llm' || payload.muteAudioTrack === 'ai_tts_asr')
      const res = await autoEditApi.mixEditPlan({
        video_ids: payload.videoIds,
        mix_audio_mode: payload.mixAudioMode,
        mute_audio_track: payload.muteAudioTrack,
        target_duration_sec: payload.targetDurationSec,
        user_prompt: payload.userPrompt,
        ...(useTtsTrack
          ? {
              tts_align: {
                ...mixEditTtsAlign,
                split_narration_by_sentence: mixEditTtsAlign.split_narration_by_sentence === true,
              },
            }
          : {}),
      })
      const plans = res.plans || []
      setAutoPlans(plans.map((p) => applyAutoBgmRealizeOptions(p)))
      toast.success(plans.length ? `混剪方案已生成（${plans.length} 个）` : '混剪方案已生成')
    } catch (e: unknown) {
      const msg = formatFastApiDetail(e) || (e as Error)?.message || '混剪方案生成失败'
      setAutoError(msg)
    } finally {
      setAutoLoading(false)
    }
  }

  async function handleAutoRealizePlan(plan: AutoEditPlanApi, index: number) {
    setAutoRealizeMsg('')
    setAutoRealizingId(plan.plan_id)
    try {
      let planForRealize = plan
      let forceTtsPipeline = false
      let ttsAlignPayload: TtsVideoAlignConfigApi | undefined
      if (mode === 'voiceover') {
        if (voiceoverRedubEnabled) {
          if (!voiceoverPlanSupportsRedub(planForRealize)) {
            const msg =
              '重新配音要求每一段成片均有 ASR 文案。当前方案含有非 ASR 段（例如音频粗剪占位），请改用极速/智能快剪或完成语音识别后再试。'
            setAutoRealizeMsg(msg)
            toast.error(msg)
            return
          }
          planForRealize = buildVoiceoverRedubPlan(planForRealize)
          forceTtsPipeline = true
          ttsAlignPayload = { ...voiceoverTtsAlign }
        }
        const voBgm = buildVoiceoverBgmPlanPayload()
        if (voBgm) {
          planForRealize = { ...planForRealize, bgm: voBgm }
        }
      }
      if (mode === 'mix_edit' && planForRealize.mode === 'voiceover') {
        forceTtsPipeline = true
        ttsAlignPayload = {
          ...mixEditTtsAlign,
          split_narration_by_sentence: mixEditTtsAlign.split_narration_by_sentence === true,
        }
      }
      if (mode === 'mix_edit' || mode === 'auto') {
        const customBgm = buildAutoCustomBgmPlanPayload()
        if (customBgm) {
          planForRealize = { ...planForRealize, bgm: customBgm }
        }
      }
      planForRealize = applyAutoBgmRealizeOptions(planForRealize)
      const res = await autoEditApi.realize({
        plan: planForRealize,
        project_name: `autoedit_${(plan.title || `plan_${index + 1}`).slice(0, 20)}`,
        include_subtitle: subtitleEnabled,
        style: subtitleStyle,
        ...(forceTtsPipeline ? { force_tts_pipeline: true, tts_align: ttsAlignPayload } : {}),
      })
      const downloadUrl = `${API_BASE_URL}${res.url}`
      setAutoRealizeDownloads((prev) => ({
        ...prev,
        [plan.plan_id]: {
          filename: res.filename,
          url: downloadUrl,
        },
      }))
      setAutoRealizeMsg('成片已生成，请点击下方下载链接。')
    } catch (e: unknown) {
      const msg = formatFastApiDetail(e)
      setAutoRealizeMsg(msg)
      toast.error(msg)
    } finally {
      setAutoRealizingId(null)
    }
  }

  async function handleAutoExportJianyingDraft(plan: AutoEditPlanApi, index: number) {
    setAutoRealizeMsg('')
    setAutoJianyingDraftExportingId(plan.plan_id)
    try {
      let planForExport = applyAutoBgmRealizeOptions(plan)
      let forceTtsPipeline = false
      let ttsAlignPayload: TtsVideoAlignConfigApi | undefined
      if (mode === 'voiceover') {
        const voBgm = buildVoiceoverBgmPlanPayload()
        if (voiceoverRedubEnabled) {
          if (!voiceoverPlanSupportsRedub(planForExport)) {
            const msg =
              '重新配音要求每一段成片均有 ASR 文案。当前方案含有非 ASR 段（例如音频粗剪占位），请改用极速/智能快剪或完成语音识别后再试。'
            setAutoRealizeMsg(msg)
            toast.error(msg)
            setAutoJianyingDraftExportingId(null)
            return
          }
          planForExport = buildVoiceoverRedubPlan(planForExport)
          forceTtsPipeline = true
          ttsAlignPayload = { ...voiceoverTtsAlign }
        }
        if (voBgm) {
          planForExport = { ...planForExport, bgm: voBgm }
        }
      }
      if (mode === 'mix_edit' && planForExport.mode === 'voiceover') {
        forceTtsPipeline = true
        ttsAlignPayload = {
          ...mixEditTtsAlign,
          split_narration_by_sentence: mixEditTtsAlign.split_narration_by_sentence === true,
        }
      }
      const res = await autoEditApi.exportJianyingDraft({
        plan: planForExport,
        project_name: `autoedit_jy_${(plan.title || `plan_${index + 1}`).slice(0, 20)}`,
        include_subtitle: subtitleEnabled,
        style: subtitleStyle,
        ...(forceTtsPipeline ? { force_tts_pipeline: true, tts_align: ttsAlignPayload } : {}),
      })
      if (res.mode === 'direct' && res.local_path) {
        setAutoJianyingDraftDownloads((prev) => ({
          ...prev,
          [plan.plan_id]: { mode: 'direct', local_path: res.local_path },
        }))
        setAutoRealizeMsg('剪映草稿已写入本机目录，见方案卡片中的路径。')
        toast.success('剪映草稿已导出到本地')
        return
      }
      setAutoJianyingDraftDownloads((prev) => ({
        ...prev,
        [plan.plan_id]: { mode: 'zip', filename: res.filename, url: res.url },
      }))
      setAutoRealizeMsg('剪映草稿已生成，请点击方案卡片中的草稿下载链接。')
      toast.success('剪映草稿已导出')
      toastRecommendJianyingParentDir(toast)
    } catch (e: unknown) {
      const msg = formatFastApiDetail(e)
      setAutoRealizeMsg(msg)
      toast.error(msg)
    } finally {
      setAutoJianyingDraftExportingId(null)
    }
  }

  // PLACEHOLDER_JSX
  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <ExportSidebar
        segments={segments} exportMode={exportMode} setExportMode={setExportMode}
        exporting={exporting} exportError={exportError} onExport={handleExport}
        subtitleEnabled={subtitleEnabled} onToggleSubtitle={setSubtitleEnabled}
        srtReady={srtEntries.length > 0} generatingSrt={generatingSrt}
        matchMode={mode}
      />
      <div className="pr-64">
        <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
          <MatchPageHeader mode={mode} onModeChange={setMatchMode} onOpenVideoResult={() => setResultOpen(true)} />
          {doneVideos.length === 0 && mode !== 'script_stock' && (
            <div className="rounded-xl border border-amber-600/30 bg-amber-500/5 px-5 py-4 flex items-center gap-3">
              <AlertCircle className="w-5 h-5 text-amber-400" />
              <p className="text-sm text-slate-300">暂无可匹配素材，请先在<Link href="/process" className="mx-1 text-indigo-400 hover:underline">素材处理</Link>完成。</p>
            </div>
          )}
          <VideoScopeSelector
            scopeVideos={scopeVideos}
            filteredScopeVideos={filteredScopeVideos}
            pagedScopeVideos={pagedScopeVideos}
            videoSearch={videoSearch}
            videoPage={videoPage}
            videoTotalPages={videoTotalPages}
            selectedVideoIds={selectedVideoIds}
            onToggleVideo={toggleVideo}
            onSearchChange={handleVideoSearch}
            onPrevPage={() => setVideoPage((p) => Math.max(1, p - 1))}
            onNextPage={() => setVideoPage((p) => Math.min(videoTotalPages, p + 1))}
          />

          {mode === 'replica' ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-5">
              <div className="space-y-2">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">链接复刻 · 模板</p>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  在此生成或选用复刻模板。确认后请<strong className="text-slate-300">二选一</strong>进入「手动匹配」或「一键成片」——两条不同流水线，不是先后步骤；最终都可导出成片。
                </p>
              </div>
              <ReplicaTemplateLibrary
                refreshSignal={replicaTemplateRefreshSignal}
                onUse={({ guide, replicaType }) => {
                  setReplicaTemplateGuide(guide)
                  setReplicaTemplateType(replicaType)
                  toast.success('已载入模板，请选择下方要进入的流水线')
                }}
              />
              <ReplicaTemplateWizard
                initialGuide={replicaTemplateGuide}
                onTemplateSaved={() => setReplicaTemplateRefreshSignal((v) => v + 1)}
                onConfirmed={({ guide, replicaType }) => {
                  setReplicaTemplateGuide(guide)
                  setReplicaTemplateType(replicaType)
                  toast.success('模板已确认，请选择下方要进入的流水线')
                }}
              />
              <div className="rounded-xl border border-amber-500/25 bg-amber-500/5 p-4 space-y-3">
                <p className="text-xs font-semibold text-amber-200">模板就绪后，进入哪条流水线？</p>
                <div className="flex flex-col sm:flex-row flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={!replicaTemplateGuide.trim()}
                    onClick={goReplicaToManualPipeline}
                    className="flex-1 min-w-[200px] px-4 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-semibold transition-colors"
                  >
                    去手动匹配（注入复刻约束到文案生成）
                  </button>
                  <button
                    type="button"
                    disabled={!replicaTemplateGuide.trim()}
                    onClick={goReplicaToAutoPipeline}
                    className="flex-1 min-w-[200px] px-4 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-semibold transition-colors"
                  >
                    去一键成片（注入复刻约束到剪辑诉求）
                  </button>
                </div>
                <p className="text-[10px] text-slate-500">
                  手动匹配：段落检索 + TTS + 侧栏导出；一键成片：LLM 方案 + 预览 + 成片。可随时回到本页切换模板。
                </p>
              </div>
            </div>
          ) : mode === 'script_stock' ? (
            <ScriptStockPanel subtitleEnabled={subtitleEnabled} subtitleStyle={subtitleStyle} />
          ) : mode === 'auto' || mode === 'template' ? (
            <>
              {autoPrompt.trim().startsWith('【复刻模板约束】') ? (
                <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 px-4 py-3 text-xs text-emerald-200">
                  剪辑诉求已包含从「链接复刻」注入的模板约束；当前模板预设已锁定为“复刻模板”，请先补充「用户诉求」再生成方案。
                </div>
              ) : null}
            <TemplateClipPanel
              autoPrompt={autoPrompt}
              onAutoPromptChange={setAutoPrompt}
              autoMode={autoMode}
              onAutoModeChange={setAutoMode}
              autoTargetDuration={autoTargetDuration}
              onAutoTargetDurationChange={setAutoTargetDuration}
              autoNumPlans={autoNumPlans}
              onAutoNumPlansChange={setAutoNumPlans}
              autoBgmMixEnabled={autoBgmMixEnabled}
              onAutoBgmMixEnabledChange={setAutoBgmMixEnabled}
              autoBgmPlanPolicy={autoBgmPlanPolicy}
              onAutoBgmPlanPolicyChange={setAutoBgmPlanPolicy}
              autoBgmTrackFilename={autoBgmTrackFilename}
              onAutoBgmTrackFilenameChange={setAutoBgmTrackFilename}
                showAutoCustomBgmConfig={showAutoCustomBgmConfig}
                autoCustomBgmEnabled={autoCustomBgmEnabled}
                onAutoCustomBgmEnabledChange={setAutoCustomBgmEnabled}
                autoCustomBgmTrackIds={autoCustomBgmTrackIds}
                onToggleAutoCustomBgmTrack={(trackId) => {
                  setAutoCustomBgmTrackIds((prev) =>
                    prev.includes(trackId) ? prev.filter((id) => id !== trackId) : [...prev, trackId]
                  )
                }}
                autoCustomBgmVolumeByTrackId={autoCustomBgmVolumeByTrackId}
                onAutoCustomBgmTrackVolumeChange={(trackId, volumeDb) => {
                  setAutoCustomBgmVolumeByTrackId((prev) => ({ ...prev, [trackId]: volumeDb }))
                }}
                autoCustomBgmTimelineSegments={autoCustomBgmTimelineSegments}
                onAddAutoCustomBgmTimelineSegment={() => {
                  setAutoCustomBgmTimelineSegments((prev) => [
                    ...prev,
                    { id: `abgm_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, startSec: 0, endSec: 10 },
                  ])
                }}
                onRemoveAutoCustomBgmTimelineSegment={(id) => {
                  setAutoCustomBgmTimelineSegments((prev) => prev.filter((seg) => seg.id !== id))
                }}
                onUpdateAutoCustomBgmTimelineSegment={(id, patch) => {
                  setAutoCustomBgmTimelineSegments((prev) =>
                    prev.map((seg) => (seg.id === id ? { ...seg, ...patch } : seg))
                  )
                }}
              autoUseTimelineEngine={autoUseTimelineEngine}
              onAutoUseTimelineEngineChange={setAutoUseTimelineEngine}
              processingProfileLocked={mode === 'template' || autoTemplateEnabled}
              processingProfileHint={
                mode === 'template' || autoTemplateEnabled
                  ? `已按模板自动匹配长视频处理档位：${contentStyleLabel(
                      mapTemplatePresetToContentStyle(templatePreset || '')
                    )}（可在高级参数中覆盖批处理细项）`
                  : undefined
              }
              autoContentStyle={autoContentStyle}
              onAutoContentStyleChange={setAutoContentStyle}
              autoEventsAdvancedEnabled={autoEventsAdvancedEnabled}
              onAutoEventsAdvancedEnabledChange={setAutoEventsAdvancedEnabled}
              autoEventsMaxClipsPerBatch={autoEventsMaxClipsPerBatch}
              onAutoEventsMaxClipsPerBatchChange={setAutoEventsMaxClipsPerBatch}
              autoEventsMaxCharsPerBatch={autoEventsMaxCharsPerBatch}
              onAutoEventsMaxCharsPerBatchChange={setAutoEventsMaxCharsPerBatch}
              autoEventsBatchOverlapClips={autoEventsBatchOverlapClips}
              onAutoEventsBatchOverlapClipsChange={setAutoEventsBatchOverlapClips}
              autoEventsMaxBatches={autoEventsMaxBatches}
              onAutoEventsMaxBatchesChange={setAutoEventsMaxBatches}
              recommendedProfile={recommendedProfile}
              estimatedBatches={estimatedBatches}
              estimatedSeconds={estimatedSeconds}
              estimatedTotalClips={estimatedTotalClips}
              onResetAdvancedToRecommended={() => {
                setAutoEventsAdvancedEnabled(true)
                setAutoEventsMaxClipsPerBatch(recommendedProfile.clips)
                setAutoEventsMaxCharsPerBatch(recommendedProfile.chars)
                setAutoEventsBatchOverlapClips(recommendedProfile.overlap)
                setAutoEventsMaxBatches(recommendedProfile.batches)
              }}
              autoExplain={autoExplain}
              onAutoExplainChange={setAutoExplain}
              autoLoading={autoLoading}
              autoError={autoError}
              autoPlans={autoPlans}
              autoExpandedPlanIds={autoExpandedPlanIds}
              onTogglePlanExpand={toggleAutoExpandedPlan}
              autoRealizingId={autoRealizingId}
              autoRealizeMsg={autoRealizeMsg}
              autoRealizeDownloads={autoRealizeDownloads}
              autoPlanLogs={autoPlanLogs}
              autoPlanElapsedSec={autoPlanElapsedSec}
              autoPlanStage={autoPlanStage}
              autoPlanStagePercent={autoPlanStagePercent}
              subtitleEnabled={subtitleEnabled}
              templatePresetSource={templatePresetSource}
              onReleaseReplicaTemplateLock={() => {
                setReplicaTemplateGuide('')
                setReplicaTemplateType('')
                setTemplatePresetSource('library')
                if (templatePreset === REPLICA_LOCKED_TEMPLATE_PRESET || templatePreset.startsWith('replica_')) setTemplatePreset('ecommerce')
                toast.success('已解除复刻模板锁定，可自由选择模板')
              }}
              onGeneratePlans={handleGenerateAutoPlans}
              onRealizePlan={handleAutoRealizePlan}
              autoJianyingDraftExportingId={autoJianyingDraftExportingId}
              autoJianyingDraftDownloads={autoJianyingDraftDownloads}
              onExportJianyingDraft={handleAutoExportJianyingDraft}
            />
            </>
          ) : mode === 'mix_edit' ? (
            <>
              <MixEditPanel
                selectedVideoIds={selectedVideoIds}
                doneVideos={scopeVideos}
                loading={autoLoading}
                onGenerate={handleMixEditPlan}
                ttsAlign={mixEditTtsAlign}
                onTtsAlignChange={(patch) =>
                  setMixEditTtsAlign((prev) => ({ ...prev, ...patch }))
                }
              />
              <AutoEditPanel
                hideLlmPlannerUi
                autoPrompt={autoPrompt}
                onAutoPromptChange={setAutoPrompt}
                autoMode={autoMode}
                onAutoModeChange={setAutoMode}
                autoTargetDuration={autoTargetDuration}
                onAutoTargetDurationChange={setAutoTargetDuration}
                autoNumPlans={autoNumPlans}
                onAutoNumPlansChange={setAutoNumPlans}
                autoBgmMixEnabled={autoBgmMixEnabled}
                onAutoBgmMixEnabledChange={setAutoBgmMixEnabled}
                autoBgmPlanPolicy={autoBgmPlanPolicy}
                onAutoBgmPlanPolicyChange={setAutoBgmPlanPolicy}
                autoBgmTrackFilename={autoBgmTrackFilename}
                onAutoBgmTrackFilenameChange={setAutoBgmTrackFilename}
                autoUseTimelineEngine={autoUseTimelineEngine}
                onAutoUseTimelineEngineChange={setAutoUseTimelineEngine}
                processingProfileLocked={false}
                autoContentStyle={autoContentStyle}
                onAutoContentStyleChange={setAutoContentStyle}
                autoEventsAdvancedEnabled={autoEventsAdvancedEnabled}
                onAutoEventsAdvancedEnabledChange={setAutoEventsAdvancedEnabled}
                autoEventsMaxClipsPerBatch={autoEventsMaxClipsPerBatch}
                onAutoEventsMaxClipsPerBatchChange={setAutoEventsMaxClipsPerBatch}
                autoEventsMaxCharsPerBatch={autoEventsMaxCharsPerBatch}
                onAutoEventsMaxCharsPerBatchChange={setAutoEventsMaxCharsPerBatch}
                autoEventsBatchOverlapClips={autoEventsBatchOverlapClips}
                onAutoEventsBatchOverlapClipsChange={setAutoEventsBatchOverlapClips}
                autoEventsMaxBatches={autoEventsMaxBatches}
                onAutoEventsMaxBatchesChange={setAutoEventsMaxBatches}
                recommendedProfile={recommendedProfile}
                estimatedBatches={estimatedBatches}
                estimatedSeconds={estimatedSeconds}
                estimatedTotalClips={estimatedTotalClips}
                onResetAdvancedToRecommended={() => {
                  setAutoEventsAdvancedEnabled(true)
                  setAutoEventsMaxClipsPerBatch(recommendedProfile.clips)
                  setAutoEventsMaxCharsPerBatch(recommendedProfile.chars)
                  setAutoEventsBatchOverlapClips(recommendedProfile.overlap)
                  setAutoEventsMaxBatches(recommendedProfile.batches)
                }}
                autoExplain={autoExplain}
                onAutoExplainChange={setAutoExplain}
                autoLoading={autoLoading}
                autoError={autoError}
                autoPlans={autoPlans}
                autoExpandedPlanIds={autoExpandedPlanIds}
                onTogglePlanExpand={toggleAutoExpandedPlan}
                autoRealizingId={autoRealizingId}
                autoRealizeMsg={autoRealizeMsg}
                autoRealizeDownloads={autoRealizeDownloads}
                autoPlanLogs={autoPlanLogs}
                autoPlanElapsedSec={autoPlanElapsedSec}
                autoPlanStage={autoPlanStage}
                autoPlanStagePercent={autoPlanStagePercent}
                subtitleEnabled={subtitleEnabled}
                onGeneratePlans={() => {}}
                onRealizePlan={handleAutoRealizePlan}
                autoJianyingDraftExportingId={autoJianyingDraftExportingId}
                autoJianyingDraftDownloads={autoJianyingDraftDownloads}
                onExportJianyingDraft={handleAutoExportJianyingDraft}
              />
            </>
          ) : mode === 'voiceover' ? (
            <>
              <VoiceoverQuickCutPanel
                selectedVideoIds={selectedVideoIds}
                doneVideos={scopeVideos}
                onGenerate={handleVoiceoverQuickCut}
                redubEnabled={voiceoverRedubEnabled}
                onRedubEnabledChange={setVoiceoverRedubEnabled}
                ttsAlign={voiceoverTtsAlign}
                onTtsAlignChange={(patch) =>
                  setVoiceoverTtsAlign((prev) => ({
                    ...prev,
                    ...patch,
                  }))
                }
              />
              <AutoEditPanel
                hideLlmPlannerUi
                autoPrompt={autoPrompt}
                onAutoPromptChange={setAutoPrompt}
                autoMode={autoMode}
                onAutoModeChange={setAutoMode}
                autoTargetDuration={autoTargetDuration}
                onAutoTargetDurationChange={setAutoTargetDuration}
                autoNumPlans={autoNumPlans}
                onAutoNumPlansChange={setAutoNumPlans}
                autoBgmMixEnabled={autoBgmMixEnabled}
                onAutoBgmMixEnabledChange={setAutoBgmMixEnabled}
                autoBgmPlanPolicy={autoBgmPlanPolicy}
                onAutoBgmPlanPolicyChange={setAutoBgmPlanPolicy}
                autoBgmTrackFilename={autoBgmTrackFilename}
                onAutoBgmTrackFilenameChange={setAutoBgmTrackFilename}
                showAutoCustomBgmConfig={showAutoCustomBgmConfig}
                autoCustomBgmEnabled={autoCustomBgmEnabled}
                onAutoCustomBgmEnabledChange={setAutoCustomBgmEnabled}
                autoCustomBgmTrackIds={autoCustomBgmTrackIds}
                onToggleAutoCustomBgmTrack={(trackId) => {
                  setAutoCustomBgmTrackIds((prev) =>
                    prev.includes(trackId) ? prev.filter((id) => id !== trackId) : [...prev, trackId]
                  )
                }}
                autoCustomBgmVolumeByTrackId={autoCustomBgmVolumeByTrackId}
                onAutoCustomBgmTrackVolumeChange={(trackId, volumeDb) => {
                  setAutoCustomBgmVolumeByTrackId((prev) => ({ ...prev, [trackId]: volumeDb }))
                }}
                autoCustomBgmTimelineSegments={autoCustomBgmTimelineSegments}
                onAddAutoCustomBgmTimelineSegment={() => {
                  setAutoCustomBgmTimelineSegments((prev) => [
                    ...prev,
                    { id: `abgm_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, startSec: 0, endSec: 10 },
                  ])
                }}
                onRemoveAutoCustomBgmTimelineSegment={(id) => {
                  setAutoCustomBgmTimelineSegments((prev) => prev.filter((seg) => seg.id !== id))
                }}
                onUpdateAutoCustomBgmTimelineSegment={(id, patch) => {
                  setAutoCustomBgmTimelineSegments((prev) =>
                    prev.map((seg) => (seg.id === id ? { ...seg, ...patch } : seg))
                  )
                }}
                showVoiceoverBgmConfig={showVoiceoverBgmConfig}
                voiceoverBgmEnabled={voiceoverBgmEnabled}
                onVoiceoverBgmEnabledChange={setVoiceoverBgmEnabled}
                bgmTracksForVoiceover={bgmTracks}
                bgmListErrorForVoiceover={bgmListError}
                selectedVoiceoverBgmTrackIds={voiceoverBgmTrackIds}
                onToggleVoiceoverBgmTrack={(trackId) => {
                  setVoiceoverBgmTrackIds((prev) => (
                    prev.includes(trackId) ? prev.filter((id) => id !== trackId) : [...prev, trackId]
                  ))
                }}
                voiceoverBgmVolumeByTrackId={voiceoverBgmVolumeByTrackId}
                onVoiceoverBgmTrackVolumeChange={(trackId, volumeDb) => {
                  setVoiceoverBgmVolumeByTrackId((prev) => ({ ...prev, [trackId]: volumeDb }))
                }}
                voiceoverBgmTimelineSegments={voiceoverBgmTimelineSegments}
                onAddVoiceoverBgmTimelineSegment={() => {
                  setVoiceoverBgmTimelineSegments((prev) => [
                    ...prev,
                    { id: `vobgm_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, startSec: 0, endSec: 10 },
                  ])
                }}
                onRemoveVoiceoverBgmTimelineSegment={(id) => {
                  setVoiceoverBgmTimelineSegments((prev) => prev.filter((seg) => seg.id !== id))
                }}
                onUpdateVoiceoverBgmTimelineSegment={(id, patch) => {
                  setVoiceoverBgmTimelineSegments((prev) =>
                    prev.map((seg) => (seg.id === id ? { ...seg, ...patch } : seg))
                  )
                }}
                autoUseTimelineEngine={autoUseTimelineEngine}
                onAutoUseTimelineEngineChange={setAutoUseTimelineEngine}
                processingProfileLocked={false}
                autoContentStyle={autoContentStyle}
                onAutoContentStyleChange={setAutoContentStyle}
                autoEventsAdvancedEnabled={autoEventsAdvancedEnabled}
                onAutoEventsAdvancedEnabledChange={setAutoEventsAdvancedEnabled}
                autoEventsMaxClipsPerBatch={autoEventsMaxClipsPerBatch}
                onAutoEventsMaxClipsPerBatchChange={setAutoEventsMaxClipsPerBatch}
                autoEventsMaxCharsPerBatch={autoEventsMaxCharsPerBatch}
                onAutoEventsMaxCharsPerBatchChange={setAutoEventsMaxCharsPerBatch}
                autoEventsBatchOverlapClips={autoEventsBatchOverlapClips}
                onAutoEventsBatchOverlapClipsChange={setAutoEventsBatchOverlapClips}
                autoEventsMaxBatches={autoEventsMaxBatches}
                onAutoEventsMaxBatchesChange={setAutoEventsMaxBatches}
                recommendedProfile={recommendedProfile}
                estimatedBatches={estimatedBatches}
                estimatedSeconds={estimatedSeconds}
                estimatedTotalClips={estimatedTotalClips}
                onResetAdvancedToRecommended={() => {
                  setAutoEventsAdvancedEnabled(true)
                  setAutoEventsMaxClipsPerBatch(recommendedProfile.clips)
                  setAutoEventsMaxCharsPerBatch(recommendedProfile.chars)
                  setAutoEventsBatchOverlapClips(recommendedProfile.overlap)
                  setAutoEventsMaxBatches(recommendedProfile.batches)
                }}
                autoExplain={autoExplain}
                onAutoExplainChange={setAutoExplain}
                autoLoading={autoLoading}
                autoError={autoError}
                autoPlans={autoPlans}
                autoExpandedPlanIds={autoExpandedPlanIds}
                onTogglePlanExpand={toggleAutoExpandedPlan}
                autoRealizingId={autoRealizingId}
                autoRealizeMsg={autoRealizeMsg}
                autoRealizeDownloads={autoRealizeDownloads}
                autoPlanLogs={autoPlanLogs}
                autoPlanElapsedSec={autoPlanElapsedSec}
                autoPlanStage={autoPlanStage}
                autoPlanStagePercent={autoPlanStagePercent}
                subtitleEnabled={subtitleEnabled}
                onGeneratePlans={() => {}}
                onRealizePlan={handleAutoRealizePlan}
                autoJianyingDraftExportingId={autoJianyingDraftExportingId}
                autoJianyingDraftDownloads={autoJianyingDraftDownloads}
                onExportJianyingDraft={handleAutoExportJianyingDraft}
              />
            </>
          ) : (
            <>
              {replicaTemplateGuide.trim() ? (
                <div className="rounded-xl border border-indigo-500/25 bg-indigo-500/5 px-4 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                  <p className="text-xs text-indigo-200">
                    已载入链接复刻模板约束，将用于下方「AI 文案生成」的创作诉求前缀。
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      setReplicaTemplateGuide('')
                      setReplicaTemplateType('')
                      setTemplatePresetSource('library')
                      toast.success('已清除复刻模板约束')
                    }}
                    className="shrink-0 text-xs text-slate-400 hover:text-red-300 border border-slate-700 rounded-lg px-3 py-1.5"
                  >
                    清除约束
                  </button>
                </div>
              ) : null}
              <ManualMatchPanel
                topK={topK}
                topN={topN}
                onTopKChange={setTopK}
                onTopNChange={setTopN}
                selectedVideoIds={effectiveCopyGenVideoIds}
                onAiApply={handleAiApply}
                globalQuery={globalQuery}
                onGlobalQueryChange={setGlobalQuery}
                onSplit={splitGlobalQuery}
                onMatchAll={matchAll}
                globalMatching={globalMatching}
                onSynthesiseAllTts={synthesiseAllTts}
                globalTtsSynthesising={globalTtsSynthesising}
                onAddSegment={() => addSegment()}
                onMoveSegment={moveSegment}
                onSegmentReorder={moveSegmentRel}
                segments={segments}
                onClearAll={() => setMatchSegments([])}
                onSegmentTextChange={(segId, text) => patchSeg(segId, { text })}
                onRemoveSegment={removeSegment}
                onMatchSegment={matchSegment}
                onToggleClipSelected={toggleClipSelected}
                onSynthesiseTts={synthesiseTts}
                onPlayAudio={(segId) => {
                  const seg = segments.find((s) => s.id === segId)
                  if (seg?.ttsFilename) playAudio(segId, seg.ttsFilename)
                }}
                onStopAudio={stopAudio}
                onSeekAudio={(segId, t) => {
                  if (playingSegId !== segId) return
                  seekAudio(t)
                }}
                playingSegId={playingSegId}
                audioCurrentTime={audioCurrentTime}
                audioDuration={audioDuration}
                onPreview={setPreviewClip}
                replicaTemplateGuide={replicaTemplateGuide || undefined}
                manualBgmEnabled={manualBgmEnabled}
                onManualBgmEnabledChange={setManualBgmEnabled}
                bgmTracks={bgmTracks}
                selectedManualBgmTrackIds={manualBgmTrackIds}
                onToggleManualBgmTrack={(trackId) => {
                  setManualBgmTrackIds((prev) => (
                    prev.includes(trackId) ? prev.filter((id) => id !== trackId) : [...prev, trackId]
                  ))
                }}
                manualBgmVolumeByTrackId={manualBgmVolumeByTrackId}
                onManualBgmTrackVolumeChange={(trackId, volumeDb) => {
                  setManualBgmVolumeByTrackId((prev) => ({ ...prev, [trackId]: volumeDb }))
                }}
                manualBgmTimelineSegments={manualBgmTimelineSegments}
                onAddManualBgmTimelineSegment={() => {
                  setManualBgmTimelineSegments((prev) => [
                    ...prev,
                    { id: `bgmseg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, startSec: 0, endSec: 10 },
                  ])
                }}
                onRemoveManualBgmTimelineSegment={(id) => {
                  setManualBgmTimelineSegments((prev) => prev.filter((seg) => seg.id !== id))
                }}
                onUpdateManualBgmTimelineSegment={(id, patch) => {
                  setManualBgmTimelineSegments((prev) =>
                    prev.map((seg) => (seg.id === id ? { ...seg, ...patch } : seg))
                  )
                }}
                bgmListError={bgmListError}
                onToggleExpand={(segId) => {
                  const seg = segments.find((s) => s.id === segId)
                  if (!seg) return
                  patchSeg(seg.id, { expanded: !seg.expanded })
                }}
                onOpenClipInOut={setClipInOutSegId}
              />
            </>
          )}
          {/* 各模式共用：字幕样式手调 + 时间轴预览（条目由导出/成片流程生成） */}
          <MatchSubtitleWorkspace
            style={subtitleStyle}
            onStyleChange={setSubtitleStyle}
            entries={
              isAutoLikeMode(mode) ? srtEntries : exportMode === 'subtitle' || exportMode === 'jianying_tts' ? srtEntries : []
            }
            subtitleEnabled={subtitleEnabled}
            onSubtitleEnabledChange={setSubtitleEnabled}
            strictUseClientSrt={showStrictSrtToggle ? strictUseClientSrt : undefined}
            onStrictUseClientSrtChange={showStrictSrtToggle ? setStrictUseClientSrt : undefined}
            timingSource={
              isAutoLikeMode(mode)
                ? timingSource
                : exportMode === 'subtitle' || exportMode === 'jianying_tts'
                  ? timingSource
                  : ''
            }
            previewVideoSize={previewVideoSize}
            previewFrameUrl={subtitlePreviewFrameUrl}
            srtError={srtError}
            footer={
              <>
                {exportMode === 'subtitle' && readySegs.length > 0 && (
                  <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-3 text-xs text-cyan-400 space-y-1">
                    <p className="font-semibold">💬 一键成片流程</p>
                    <ol className="list-decimal list-inside space-y-0.5 text-cyan-500/80">
                      <li>读取已合成 TTS 音频的实际时长（ffprobe）</li>
                      <li>LLM 自动生成精确字幕时间轴</li>
                      <li>ffmpeg 合并视频 + 替换音轨 + ASS 字幕硬烧</li>
                      <li>输出带字幕完整 MP4</li>
                    </ol>
                    {generatingSrt && (
                      <p className="flex items-center gap-2 text-amber-400 mt-1">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        正在生成字幕时间轴...
                      </p>
                    )}
                  </div>
                )}

                {exportMode === 'original' && readySegs.length > 0 && (
                  <div className="rounded-xl border border-slate-500/20 bg-slate-500/5 px-4 py-3 text-xs text-slate-200 space-y-1">
                    <p className="font-semibold">🔇 原声成片流程</p>
                    <ol className="list-decimal list-inside space-y-0.5 text-slate-300/80">
                      <li>按当前段落的选中 clip 组计算总时长</li>
                      <li>跳过 TTS，直接保留原声拼接视频</li>
                      <li>对最终音频做归一化/限幅（减少音量突变）</li>
                      <li>{subtitleEnabled ? '按句子/换行等分生成字幕并硬烧' : '不生成字幕文件（仅拼接原声）'}</li>
                    </ol>
                  </div>
                )}

                {exportMode === 'jianying_tts' && readySegs.length > 0 && (
                  <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 px-4 py-3 text-xs text-emerald-200/95 space-y-1">
                    <p className="font-semibold">✂️ 剪映草稿（配音轨）</p>
                    <p className="text-emerald-200/75 text-[11px] leading-relaxed">
                      与侧栏「一键成片」互斥：本模式只打包剪映工程与素材引用，不生成 MP4。
                    </p>
                    <ol className="list-decimal list-inside space-y-0.5 text-emerald-200/70">
                      <li>各段须已合成 TTS；导出时按需生成与成片一致的字幕时间轴</li>
                      <li>后端生成 ZIP，浏览器下载后解压</li>
                      <li>按包内「路径说明」运行 patch 脚本，修正为本机绝对路径后再用剪映打开</li>
                    </ol>
                    {generatingSrt && subtitleEnabled && (
                      <p className="flex items-center gap-2 text-amber-400/90 mt-1 text-[11px]">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        正在生成字幕时间轴（用于草稿字幕轨）…
                      </p>
                    )}
                  </div>
                )}

                {exportMode === 'jianying_original' && readySegs.length > 0 && (
                  <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 px-4 py-3 text-xs text-emerald-200/95 space-y-1">
                    <p className="font-semibold">✂️ 剪映草稿（原声轨）</p>
                    <p className="text-emerald-200/75 text-[11px] leading-relaxed">
                      与侧栏「原声成片」互斥：仅 ZIP，不拼接/不烧录成片 MP4。
                    </p>
                    <ol className="list-decimal list-inside space-y-0.5 text-emerald-200/70">
                      <li>仅导出已勾选素材段落；时间轴按素材时长与侧栏「原声成片」同源逻辑</li>
                      <li>
                        {subtitleEnabled
                          ? '草稿内可含字幕轨（文案按句/换行映射到各段时长）'
                          : '不写入字幕轨，仅视频与原生音频时间线'}
                      </li>
                      <li>解压后同样需路径修补再导入剪映草稿目录</li>
                    </ol>
                  </div>
                )}
              </>
            }
          />
        </div>
      </div>
      {previewClip && <PreviewModal clip={previewClip} onClose={() => setPreviewClip(null)} />}
      <ClipInOutDialog
        open={Boolean(clipInOutSegId && clipInOutSeg && (clipInOutSeg.selectedClipIds?.length ?? 0) > 0)}
        segment={clipInOutSeg ?? null}
        onClose={() => setClipInOutSegId(null)}
        onSave={(slots) => {
          if (!clipInOutSegId) return
          const seg = useMatchStore.getState().segments.find((s) => s.id === clipInOutSegId)
          if (!seg) return
          patchSeg(seg.id, { clipTrimSlots: slots })
        }}
      />
      <VideoResultDrawer
        open={resultOpen}
        onClose={() => setResultOpen(false)}
        videoId={selectedVideoIds.length === 1 ? selectedVideoIds[0] : ''}
        videoOptions={doneVideos.map((v) => ({ id: v.id, name: v.name }))}
        title="视频处理结果（ASR / VLM / 预览 / 可编辑）"
      />
    </main>
  )
}

