'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import {
  AlertCircle, Loader2,
} from 'lucide-react'
import apiClient, { API_BASE_URL, exportApi, ttsApi, subtitleApi, type MatchClip, type Video, autoEditApi, type AutoEditPlanApi } from '@/lib/api'
import { type Segment, type SRTEntry, audioSrc } from './_components/types'
import { PreviewModal } from './_components/ClipCard'
import { ExportSidebar } from './_components/ExportSidebar'
import { SubtitlePanel } from './_components/SubtitlePanel'
import { MatchPageHeader } from './_components/MatchPageHeader'
import { VideoScopeSelector } from './_components/VideoScopeSelector'
import { ManualMatchPanel } from './_components/ManualMatchPanel'
import { AutoEditPanel } from './_components/AutoEditPanel'
import { type AutoPlanStage } from './_components/autoEditTypes'
import { useMatchStore } from '@/lib/store'

const VIDEO_PAGE_SIZE = 9

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
    autoPlans,
    setAutoPlans,
    autoRealizeDownloads,
    setAutoRealizeDownloads,
    autoExpandedPlanIds,
    setAutoExpandedPlanIds,
    autoPlanLogs,
    setAutoPlanLogs,
  } = useMatchStore()

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
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playingSegId, setPlayingSegId] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [globalMatching, setGlobalMatching] = useState(false)
  const [srtEntries, setSrtEntries] = useState<SRTEntry[]>([])
  const [timingSource, setTimingSource] = useState('')
  const [generatingSrt, setGeneratingSrt] = useState(false)
  const [srtError, setSrtError] = useState('')
  const [previewVideoSize, setPreviewVideoSize] = useState<{ width: number; height: number } | null>(null)

  // 自动成片 · 仅会话态（不持久化）
  const [autoLoading, setAutoLoading] = useState(false)
  const [autoError, setAutoError] = useState('')
  const [autoRealizingId, setAutoRealizingId] = useState<string | null>(null)
  const [autoRealizeMsg, setAutoRealizeMsg] = useState('')
  const [autoPlanStartedAt, setAutoPlanStartedAt] = useState<number | null>(null)
  const [autoPlanElapsedSec, setAutoPlanElapsedSec] = useState(0)
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

  const doneVideos = videos.filter((v) => v.status === 'done' && v.total_clips > 0)
  const filteredDoneVideos = useMemo(() => {
    const q = videoSearch.trim().toLowerCase()
    return q ? doneVideos.filter((v) => v.name.toLowerCase().includes(q)) : doneVideos
  }, [doneVideos, videoSearch])
  const videoTotalPages = Math.max(1, Math.ceil(filteredDoneVideos.length / VIDEO_PAGE_SIZE))
  const pagedDoneVideos = filteredDoneVideos.slice((videoPage - 1) * VIDEO_PAGE_SIZE, videoPage * VIDEO_PAGE_SIZE)
  const handleVideoSearch = (val: string) => { setVideoSearch(val); setVideoPage(1) }

  function makeSeg(id: string, text = ''): Segment {
    return { id, text, clips: [], chosenIdx: 0, selectedClipIds: [], ttsFilename: null, ttsLoading: false, ttsError: '', matchLoading: false, matchError: '', expanded: false }
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
    const audio = new Audio(audioSrc(filename)); audioRef.current = audio; setPlayingSegId(segId)
    audio.play(); audio.onended = () => setPlayingSegId(null); audio.onerror = () => setPlayingSegId(null)
  }
  function stopAudio() { audioRef.current?.pause(); audioRef.current = null; setPlayingSegId(null) }

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
        .map((s) => ({
          copy_text: s.text,
          clip_id: (s.selectedClipIds?.[0] ?? s.clips[s.chosenIdx]?.clip_id) ?? '',
          tts_filename: s.ttsFilename ?? undefined,
        }))
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
    setExporting(true); setExportError('')
    const projectName = globalQuery.slice(0, 30).replace(/\s+/g, '_') || 'smartclip_project'
    try {
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
            return {
              copy_text: s.text,
              clip_id: clip_ids[0] ?? '',
              clip_ids,
              tts_filename: s.ttsFilename ?? undefined,
            }
          })
          .filter((s) => s.clip_id)
        const res = await subtitleApi.burn({
          segments: segsInput,
          srt_content: currentSrt,
          style: subtitleStyle,
          project_name: projectName,
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
            return {
              copy_text: s.text,
              clip_id: clip_ids[0] ?? '',
              clip_ids,
              // 原声模式：不使用/不传 TTS
              tts_filename: undefined,
            }
          })
          .filter((s) => s.clip_id)
        const res = await subtitleApi.exportOriginal({
          segments: segsInput,
          style: subtitleStyle,
          project_name: projectName,
          include_subtitle: subtitleEnabled,
          normalize_audio: true,
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

  async function handleGenerateAutoPlans() {
    if (!autoPrompt.trim()) return
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
      const payload = {
        video_ids: selectedVideoIds.length > 0 ? selectedVideoIds : doneVideos.map((v) => v.id),
        user_prompt: autoPrompt.trim(),
        mode: autoMode,
        target_duration_sec: typeof autoTargetDuration === 'number' ? autoTargetDuration : undefined,
        num_plans: autoNumPlans,
        allow_cross_video: true,
        subtitle_policy: subtitleEnabled ? 'auto' as const : 'none' as const,
        transition_policy: 'auto' as const,
        bgm_policy: 'auto' as const,
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
            setAutoPlans(plans)
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

  async function handleAutoRealizePlan(plan: AutoEditPlanApi, index: number) {
    setAutoRealizeMsg('')
    setAutoRealizingId(plan.plan_id)
    try {
      const res = await autoEditApi.realize({
        plan,
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
          <MatchPageHeader mode={mode} onModeChange={setMatchMode} />
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

          {mode === 'auto' ? (
            <AutoEditPanel
              autoPrompt={autoPrompt}
              onAutoPromptChange={setAutoPrompt}
              autoMode={autoMode}
              onAutoModeChange={setAutoMode}
              autoTargetDuration={autoTargetDuration}
              onAutoTargetDurationChange={setAutoTargetDuration}
              autoNumPlans={autoNumPlans}
              onAutoNumPlansChange={setAutoNumPlans}
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
              onGeneratePlans={handleGenerateAutoPlans}
              onRealizePlan={handleAutoRealizePlan}
            />
          ) : (
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
              playingSegId={playingSegId}
              onPreview={setPreviewClip}
              onToggleExpand={(segId) => {
                const seg = segments.find((s) => s.id === segId)
                if (!seg) return
                patchSeg(seg.id, { expanded: !seg.expanded })
              }}
            />
          )}
          {/* 主区字幕设置：自动/手动均始终展示，便于先调样式再选导出格式；zip 不烧录字幕但状态与后续切换成片仍共用 store */}
          <SubtitlePanel
            style={subtitleStyle}
            onChange={setSubtitleStyle}
            entries={mode === 'auto' ? srtEntries : exportMode === 'subtitle' ? srtEntries : []}
            enabled={subtitleEnabled}
            onToggle={setSubtitleEnabled}
            timingSource={mode === 'auto' ? timingSource : exportMode === 'subtitle' ? timingSource : ''}
            previewVideoSize={previewVideoSize}
          />
          {srtError && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-400">字幕错误：{srtError}</div>
          )}
          {exportMode === 'subtitle' && readySegs.length > 0 && (
            <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-3 text-xs text-cyan-400 space-y-1">
              <p className="font-semibold">💬 一键成片流程</p>
              <ol className="list-decimal list-inside space-y-0.5 text-cyan-500/80">
                <li>读取已合成 TTS 音频的实际时长（ffprobe）</li>
                <li>LLM 自动生成精确字幕时间轴</li>
                <li>ffmpeg 合并视频 + 替换音轨 + ASS 字幕硬烧</li>
                <li>输出带字幕完整 MP4</li>
              </ol>
              {generatingSrt && <p className="flex items-center gap-2 text-amber-400 mt-1"><Loader2 className="w-3 h-3 animate-spin" />正在生成字幕时间轴...</p>}
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
        </div>
      </div>
      {previewClip && <PreviewModal clip={previewClip} onClose={() => setPreviewClip(null)} />}
    </main>
  )
}

