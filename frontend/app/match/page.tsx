'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import {
  AlertCircle, ArrowLeft, ChevronLeft, ChevronRight, Film, Loader2,
  Plus, Search, Sparkles, SplitSquareHorizontal,
} from 'lucide-react'
import apiClient, { API_BASE_URL, exportApi, ttsApi, subtitleApi, type MatchClip, type Video } from '@/lib/api'
import { type Segment, type SRTEntry, audioSrc } from './_components/types'
import { CopyGeneratorPanel } from './_components/CopyGeneratorPanel'
import { PreviewModal } from './_components/ClipCard'
import { SegmentRow } from './_components/SegmentRow'
import { ExportSidebar } from './_components/ExportSidebar'
import { SubtitlePanel } from './_components/SubtitlePanel'
import { useMatchStore } from '@/lib/store'

const VIDEO_PAGE_SIZE = 9

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
  const [counter, setCounter] = useState(0)
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
    const id = `seg-${counter}`; setCounter((c) => c + 1)
    setMatchSegments([...useMatchStore.getState().segments, makeSeg(id, text)])
  }
  function removeSegment(id: string) { setMatchSegments(useMatchStore.getState().segments.filter((s) => s.id !== id)) }

  function splitGlobalQuery() {
    if (!globalQuery.trim()) return
    let parts = globalQuery.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)
    if (parts.length <= 1) parts = globalQuery.split(/(?<=[。！？!?])\s*/).map((p) => p.trim()).filter(Boolean)
    if (parts.length <= 1) parts = globalQuery.split(/\n/).map((p) => p.trim()).filter(Boolean)
    if (!parts.length) return
    setCounter((c) => { setMatchSegments(parts.map((t, i) => makeSeg(`seg-${c + i}`, t))); return c + parts.length })
  }
  function handleAiApply(parts: string[]) {
    if (!parts.length) return
    setGlobalQuery(parts.join('\n\n'))
    setCounter((c) => { setMatchSegments(parts.map((t, i) => makeSeg(`seg-${c + i}`, t))); return c + parts.length })
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

  // PLACEHOLDER_JSX
  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <ExportSidebar
        segments={segments} exportMode={exportMode} setExportMode={setExportMode}
        exporting={exporting} exportError={exportError} onExport={handleExport}
        subtitleEnabled={subtitleEnabled} onToggleSubtitle={setSubtitleEnabled}
        srtReady={srtEntries.length > 0} generatingSrt={generatingSrt}
      />
      <div className="pr-64">
        <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
              <ArrowLeft className="w-4 h-4" />首页
            </Link>
            <div className="w-px h-4 bg-slate-700" />
            <h1 className="text-xl font-semibold flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-indigo-400" />文案匹配 · 配音 · 成片
            </h1>
          </div>
          {doneVideos.length === 0 && (
            <div className="rounded-xl border border-amber-600/30 bg-amber-500/5 px-5 py-4 flex items-center gap-3">
              <AlertCircle className="w-5 h-5 text-amber-400" />
              <p className="text-sm text-slate-300">暂无可匹配素材，请先在<Link href="/process" className="mx-1 text-indigo-400 hover:underline">素材处理</Link>完成。</p>
            </div>
          )}
          {doneVideos.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">限定视频范围<span className="normal-case font-normal text-slate-600 ml-1">（不选 = 全部）</span></p>
                <span className="text-xs text-slate-600">{videoSearch ? `${filteredDoneVideos.length} / ${doneVideos.length}` : doneVideos.length} 个视频</span>
              </div>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
                <input type="text" value={videoSearch} onChange={(e) => handleVideoSearch(e.target.value)} placeholder="搜索视频名称..."
                  className="w-full pl-9 pr-9 py-2 rounded-lg bg-slate-800/60 border border-slate-700 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500 transition-colors" />
                {videoSearch && <button onClick={() => handleVideoSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 text-xs">✕</button>}
              </div>
              {filteredDoneVideos.length === 0 ? (
                <p className="text-slate-500 text-sm">未找到「{videoSearch}」。</p>
              ) : (
                <>
                  <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
                    {pagedDoneVideos.map((v) => (
                      <button key={v.id} onClick={() => toggleVideo(v.id)}
                        className={`text-left px-3 py-2.5 rounded-lg border text-xs flex items-center gap-2 transition-colors ${
                          selectedVideoIds.includes(v.id) ? 'border-indigo-500 bg-indigo-500/15 text-indigo-300' : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-500'
                        }`}>
                        <Film className="w-3.5 h-3.5 shrink-0" /><span className="truncate">{v.name}</span>
                        <span className="ml-auto shrink-0 text-slate-600">{v.total_clips}片</span>
                      </button>
                    ))}
                  </div>
                  {videoTotalPages > 1 && (
                    <div className="flex items-center justify-between pt-1">
                      <button onClick={() => setVideoPage((p) => Math.max(1, p - 1))} disabled={videoPage === 1}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/40 text-xs text-slate-400 hover:border-slate-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                        <ChevronLeft className="w-3.5 h-3.5" />上一页
                      </button>
                      <span className="text-xs text-slate-500">{videoPage} / {videoTotalPages}</span>
                      <button onClick={() => setVideoPage((p) => Math.min(videoTotalPages, p + 1))} disabled={videoPage === videoTotalPages}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/40 text-xs text-slate-400 hover:border-slate-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                        下一页<ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}
                </>
              )}
            </section>
          )}
          {/* PLACEHOLDER_REST */}
          <div className="flex flex-wrap items-center gap-4">
            <label className="text-xs text-slate-500 flex items-center gap-2">初筛
              <input type="number" min={1} max={50} value={topK} onChange={(e) => setTopK(+e.target.value)}
                className="w-14 rounded-lg bg-slate-800 border border-slate-700 px-2 py-1 text-center text-slate-200" />
            </label>
            <label className="text-xs text-slate-500 flex items-center gap-2">推荐
              <input type="number" min={1} max={20} value={topN} onChange={(e) => setTopN(+e.target.value)}
                className="w-14 rounded-lg bg-slate-800 border border-slate-700 px-2 py-1 text-center text-slate-200" />
            </label>
          </div>
          <CopyGeneratorPanel selectedVideoIds={selectedVideoIds} onApply={handleAiApply} />
          <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
              <SplitSquareHorizontal className="w-4 h-4 text-slate-500" />批量拆分文案
            </p>
            <textarea value={globalQuery} onChange={(e) => setGlobalQuery(e.target.value)}
              placeholder="粘贴完整文案，按空行自动拆分为多段分别匹配..." rows={4}
              className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm outline-none focus:border-indigo-500 placeholder-slate-600 resize-none" />
            <div className="flex items-center gap-3">
              <button onClick={splitGlobalQuery} disabled={!globalQuery.trim()}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-sm flex items-center gap-2 border border-slate-700 transition-colors">
                <SplitSquareHorizontal className="w-4 h-4" />拆分为段落
              </button>
              {segments.length > 0 && (
                <button onClick={matchAll} disabled={globalMatching}
                  className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm flex items-center gap-2 transition-colors">
                  {globalMatching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                  {globalMatching ? '全部匹配中...' : '全部匹配'}
                </button>
              )}
              <button onClick={() => addSegment()}
                className="ml-auto px-3 py-2 rounded-xl border border-slate-700 bg-slate-800/40 hover:border-slate-500 text-xs text-slate-400 flex items-center gap-1.5 transition-colors">
                <Plus className="w-3.5 h-3.5" />手动添加段落
              </button>
            </div>
          </section>
          {segments.length > 0 && (
            <section className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">文案段落 · {segments.length} 段</p>
                <button onClick={() => setMatchSegments([])} className="text-xs text-slate-600 hover:text-red-400 transition-colors">清空全部</button>
              </div>
              {segments.map((seg, i) => (
                <SegmentRow key={seg.id} seg={seg} index={i}
                  onTextChange={(t) => patchSeg(seg.id, { text: t })}
                  onRemove={() => removeSegment(seg.id)}
                  onMatch={() => matchSegment(seg.id)}
                  onToggleSelect={(clipId) => toggleClipSelected(seg.id, clipId)}
                  onTts={() => synthesiseTts(seg.id)}
                  onPlayAudio={() => seg.ttsFilename && playAudio(seg.id, seg.ttsFilename)}
                  onStopAudio={stopAudio}
                  playingAudio={playingSegId === seg.id}
                  onPreview={(clip) => setPreviewClip(clip)}
                  onToggleExpand={() => patchSeg(seg.id, { expanded: !seg.expanded })}
                />
              ))}
            </section>
          )}
          {exportMode !== 'zip' && segments.length > 0 && (
            <SubtitlePanel
              style={subtitleStyle} onChange={setSubtitleStyle}
              entries={exportMode === 'subtitle' ? srtEntries : []}
              enabled={subtitleEnabled}
              onToggle={setSubtitleEnabled}
              timingSource={exportMode === 'subtitle' ? timingSource : ''}
              previewVideoSize={previewVideoSize}
            />
          )}
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

