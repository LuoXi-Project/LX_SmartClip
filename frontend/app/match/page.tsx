'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import {
  AlertCircle, Loader2,
} from 'lucide-react'
import apiClient, { API_BASE_URL, exportApi, ttsApi, subtitleApi, type MatchClip, type Video, autoEditApi, type AutoEditPlanApi, type AutoEditBgmPlanApi } from '@/lib/api'
import { type Segment, type SRTEntry, audioSrc } from './_components/types'
import { ClipInOutDialog } from './_components/ClipInOutDialog'
import { buildClipTrimsForApi } from './_components/clipTrim'
import { PreviewModal } from './_components/ClipCard'
import { ExportSidebar } from './_components/ExportSidebar'
import { MatchPageHeader } from './_components/MatchPageHeader'
import { VideoScopeSelector } from './_components/VideoScopeSelector'
import { ManualMatchPanel } from './_components/ManualMatchPanel'
import { AutoEditPanel } from './_components/AutoEditPanel'
import { VoiceoverQuickCutPanel, type VoiceoverQuickCutStrategy } from './_components/VoiceoverQuickCutPanel'
import { TemplateClipPanel } from './_components/TemplateClipPanel'
import { MatchSubtitleWorkspace } from './_components/MatchSubtitleWorkspace'
import { isAutoLikeMode } from './_components/matchModeTypes'
import { type AutoPlanStage } from './_components/autoEditTypes'
import { useMatchStore } from '@/lib/store'
import { VideoResultDrawer } from '@/app/_components/VideoResultDrawer'
import { useToast } from '@/components/ui/toast-provider'
import { ReplicaTemplateWizard } from './_components/ReplicaTemplateWizard'
import { ReplicaTemplateLibrary } from './_components/ReplicaTemplateLibrary'

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
  const [srtEntries, setSrtEntries] = useState<SRTEntry[]>([])
  const [timingSource, setTimingSource] = useState('')
  const [generatingSrt, setGeneratingSrt] = useState(false)
  const [srtError, setSrtError] = useState('')
  const [previewVideoSize, setPreviewVideoSize] = useState<{ width: number; height: number } | null>(null)
  const [resultOpen, setResultOpen] = useState(false)
  const [replicaTemplateRefreshSignal, setReplicaTemplateRefreshSignal] = useState(0)

  // 自动成片 · 仅会话态（不持久化）
  const [autoLoading, setAutoLoading] = useState(false)
  const [autoError, setAutoError] = useState('')
  const [autoRealizingId, setAutoRealizingId] = useState<string | null>(null)
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
    apiClient.get<unknown, { items: Video[] } | Video[]>('/api/videos')
      .then((d) => { if (Array.isArray(d)) setVideos(d); else setVideos((d as { items: Video[] })?.items || []) })
      .catch(console.error)
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
  const selectedOrAllDoneVideos = useMemo(
    () =>
      selectedVideoIds.length > 0
        ? doneVideos.filter((v) => selectedVideoIds.includes(v.id))
        : doneVideos,
    [doneVideos, selectedVideoIds]
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
    const valid = new Set(doneVideos.map((v) => v.id))
    const prev = useMatchStore.getState().selectedVideoIds
    const next = prev.filter((id) => valid.has(id))
    if (next.length !== prev.length) {
      setMatchSelectedVideoIds(next)
    }
  }, [doneVideos, setMatchSelectedVideoIds])
  const filteredDoneVideos = useMemo(() => {
    const q = videoSearch.trim().toLowerCase()
    return q ? doneVideos.filter((v) => v.name.toLowerCase().includes(q)) : doneVideos
  }, [doneVideos, videoSearch])
  const videoTotalPages = Math.max(1, Math.ceil(filteredDoneVideos.length / VIDEO_PAGE_SIZE))
  const pagedDoneVideos = filteredDoneVideos.slice((videoPage - 1) * VIDEO_PAGE_SIZE, videoPage * VIDEO_PAGE_SIZE)
  const handleVideoSearch = (val: string) => { setVideoSearch(val); setVideoPage(1) }

  function makeSeg(id: string, text = ''): Segment {
    return {
      id, text, clips: [], chosenIdx: 0, selectedClipIds: [], clipTrimByClipId: {},
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
      patchSeg(id, { clips, chosenIdx: 0, selectedClipIds: defaultSelected, matchLoading: false })
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

  function buildSegmentClipIds(seg: Segment): string[] {
    const primary = seg.selectedClipIds?.[0] || seg.clips[seg.chosenIdx]?.clip_id
    const ordered = [
      ...(primary ? [primary] : []),
      ...(seg.selectedClipIds ?? []),
      ...seg.clips.map((c) => c.clip_id),
    ]
    return Array.from(new Set(ordered.filter(Boolean)))
  }

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
      // 一键成片（配音 + 字幕烧录）：先在前端拦截未完成配音，避免后端因缺音频报错
      if (exportMode === 'subtitle') {
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
            const clip_ids = buildSegmentClipIds(s)
            const cid = clip_ids[0] ?? ''
            const clip_trims = buildClipTrimsForApi(s, clip_ids)
            return {
              copy_text: s.text,
              clip_id: cid,
              clip_ids,
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
        })
        const downloadUrl = `${API_BASE_URL}/api/subtitle/download/${res.filename}`
        const a = document.createElement('a')
        a.href = downloadUrl
        a.download = res.filename
        a.click()
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
        })
        const downloadUrl = `${API_BASE_URL}/api/subtitle/download/${res.filename}`
        const a = document.createElement('a')
        a.href = downloadUrl
        a.download = res.filename
        a.click()
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

  function toggleClipSelected(segId: string, clipId: string) {
    const seg = useMatchStore.getState().segments.find((s) => s.id === segId)
    if (!seg) return

    const prev = seg.selectedClipIds ?? []
    const next = prev.includes(clipId) ? prev.filter((x) => x !== clipId) : [...prev, clipId]
    const primaryId = next[0] ?? ''
    const nextChosenIdx = primaryId ? Math.max(0, seg.clips.findIndex((c) => c.clip_id === primaryId)) : 0
    patchSeg(segId, { selectedClipIds: next, chosenIdx: nextChosenIdx })
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
    if (!autoBgmMixEnabled) {
      return { ...plan, bgm: { ...baseBgm(), enabled: false } }
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
  }) {
    setAutoError('')
    setAutoLoading(true)
    try {
      const res = await autoEditApi.voiceoverQuickCut({
        video_ids: payload.videoIds,
        strategy: payload.strategy,
        user_prompt: payload.userPrompt,
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

  async function handleAutoRealizePlan(plan: AutoEditPlanApi, index: number) {
    setAutoRealizeMsg('')
    setAutoRealizingId(plan.plan_id)
    try {
      const planForRealize = applyAutoBgmRealizeOptions(plan)
      const res = await autoEditApi.realize({
        plan: planForRealize,
        project_name: `autoedit_${(plan.title || `plan_${index + 1}`).slice(0, 20)}`,
        include_subtitle: subtitleEnabled,
        style: subtitleStyle,
      })
      const downloadUrl = `${API_BASE_URL}${res.url}`
      setAutoRealizeDownloads((prev) => ({
        ...prev,
        [plan.plan_id]: { filename: res.filename, url: downloadUrl },
      }))
      setAutoRealizeMsg('成片已生成，请点击下方下载链接。')
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '一键成片失败'
      setAutoRealizeMsg(msg)
    } finally {
      setAutoRealizingId(null)
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
          {doneVideos.length === 0 && (
            <div className="rounded-xl border border-amber-600/30 bg-amber-500/5 px-5 py-4 flex items-center gap-3">
              <AlertCircle className="w-5 h-5 text-amber-400" />
              <p className="text-sm text-slate-300">暂无可匹配素材，请先在<Link href="/process" className="mx-1 text-indigo-400 hover:underline">素材处理</Link>完成。</p>
            </div>
          )}
          <VideoScopeSelector
            doneVideos={doneVideos}
            filteredDoneVideos={filteredDoneVideos}
            pagedDoneVideos={pagedDoneVideos}
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
            />
            </>
          ) : mode === 'voiceover' ? (
            <>
              <VoiceoverQuickCutPanel
                selectedVideoIds={selectedVideoIds}
                doneVideos={doneVideos}
                onGenerate={handleVoiceoverQuickCut}
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
                selectedVideoIds={selectedVideoIds}
                onAiApply={handleAiApply}
                globalQuery={globalQuery}
                onGlobalQueryChange={setGlobalQuery}
                onSplit={splitGlobalQuery}
                onMatchAll={matchAll}
                globalMatching={globalMatching}
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
            entries={isAutoLikeMode(mode) ? srtEntries : exportMode === 'subtitle' ? srtEntries : []}
            subtitleEnabled={subtitleEnabled}
            onSubtitleEnabledChange={setSubtitleEnabled}
            timingSource={isAutoLikeMode(mode) ? timingSource : exportMode === 'subtitle' ? timingSource : ''}
            previewVideoSize={previewVideoSize}
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
        onSave={(trims) => {
          if (!clipInOutSegId) return
          const seg = useMatchStore.getState().segments.find((s) => s.id === clipInOutSegId)
          if (!seg) return
          patchSeg(seg.id, { clipTrimByClipId: { ...(seg.clipTrimByClipId ?? {}), ...trims } })
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

