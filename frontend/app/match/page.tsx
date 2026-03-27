'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import {
  AlertCircle, ArrowLeft, Film, Loader2,
  Plus, Search, Sparkles, SplitSquareHorizontal,
} from 'lucide-react'
import apiClient, { exportApi, ttsApi, type MatchClip, type MergedSegment, type Video } from '@/lib/api'
import { type Segment, type ExportMode, audioSrc } from './_components/types'
import { PreviewModal } from './_components/ClipCard'
import { SegmentRow } from './_components/SegmentRow'
import { ExportSidebar } from './_components/ExportSidebar'

export default function MatchPage() {
  const [videos, setVideos] = useState<Video[]>([])
  const [selectedVideoIds, setSelectedVideoIds] = useState<string[]>([])
  const [topK, setTopK] = useState(12)
  const [topN, setTopN] = useState(5)
  const [globalQuery, setGlobalQuery] = useState('')
  const [segments, setSegments] = useState<Segment[]>([])
  const [counter, setCounter] = useState(0)
  const [previewClip, setPreviewClip] = useState<MatchClip | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playingSegId, setPlayingSegId] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [exportMode, setExportMode] = useState<ExportMode>('zip')
  const [globalMatching, setGlobalMatching] = useState(false)

  useEffect(() => {
    apiClient.get<unknown, { items: Video[] } | Video[]>('/api/videos')
      .then((d) => {
        if (Array.isArray(d)) setVideos(d)
        else setVideos((d as { items: Video[] })?.items || [])
      })
      .catch(console.error)
  }, [])

  const doneVideos = videos.filter((v) => v.status === 'done' && v.total_clips > 0)

  function makeSeg(id: string, text = ''): Segment {
    return { id, text, clips: [], chosenIdx: 0, ttsFilename: null, ttsLoading: false, ttsError: '', matchLoading: false, matchError: '', expanded: false }
  }

  function patchSeg(id: string, patch: Partial<Segment>) {
    setSegments((prev) => prev.map((s) => s.id === id ? { ...s, ...patch } : s))
  }

  function addSegment(text = '') {
    const id = `seg-${counter}`
    setCounter((c) => c + 1)
    setSegments((prev) => [...prev, makeSeg(id, text)])
  }

  function removeSegment(id: string) {
    setSegments((prev) => prev.filter((s) => s.id !== id))
  }

  function splitGlobalQuery() {
    if (!globalQuery.trim()) return
    // 1st pass: split by blank lines
    let parts = globalQuery.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)
    // 2nd pass: if still only 1 chunk, split by sentence-ending punctuation
    if (parts.length <= 1) {
      parts = globalQuery
        .split(/(?<=[。！？!?])\s*/)
        .map((p) => p.trim())
        .filter(Boolean)
    }
    // 3rd pass: if still 1 chunk, split by newlines
    if (parts.length <= 1) {
      parts = globalQuery.split(/\n/).map((p) => p.trim()).filter(Boolean)
    }
    if (parts.length === 0) return
    setCounter((c) => {
      setSegments(parts.map((text, i) => makeSeg(`seg-${c + i}`, text)))
      return c + parts.length
    })
  }

  async function matchSegment(id: string) {
    const seg = segments.find((s) => s.id === id)
    if (!seg || !seg.text.trim()) return
    patchSeg(id, { matchLoading: true, matchError: '' })
    try {
      const data = await apiClient.post<unknown, { recommended: MatchClip[]; candidates: MatchClip[] }>('/api/match', {
        query: seg.text.trim(), top_k: topK, top_n: topN,
        video_ids: selectedVideoIds.length > 0 ? selectedVideoIds : null,
      })
      const clips = data.recommended?.length ? data.recommended : data.candidates
      patchSeg(id, { clips, chosenIdx: 0, matchLoading: false })
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      patchSeg(id, { matchLoading: false, matchError: detail || '匹配失败' })
    }
  }

  async function matchAll() {
    setGlobalMatching(true)
    await Promise.all(segments.map((s) => matchSegment(s.id)))
    setGlobalMatching(false)
  }

  async function synthesiseTts(id: string) {
    const seg = segments.find((s) => s.id === id)
    if (!seg || !seg.text.trim()) return
    patchSeg(id, { ttsLoading: true, ttsError: '' })
    try {
      const res = await ttsApi.synthesize({ text: seg.text.trim() })
      patchSeg(id, { ttsLoading: false, ttsFilename: res.filename })
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      patchSeg(id, { ttsLoading: false, ttsError: detail || 'TTS 合成失败' })
    }
  }

  function playAudio(segId: string, filename: string) {
    audioRef.current?.pause()
    const audio = new Audio(audioSrc(filename))
    audioRef.current = audio
    setPlayingSegId(segId)
    audio.play()
    audio.onended = () => setPlayingSegId(null)
    audio.onerror = () => setPlayingSegId(null)
  }

  function stopAudio() {
    audioRef.current?.pause()
    audioRef.current = null
    setPlayingSegId(null)
  }

  const readySegs = segments.filter((s) => s.clips.length > 0)

  async function handleExport() {
    if (exporting || readySegs.length === 0) return
    setExporting(true)
    setExportError('')
    const projectName = globalQuery.slice(0, 30).replace(/\s+/g, '_') || 'smartclip_project'
    try {
      if (exportMode === 'zip') {
        const clipIds = readySegs.map((s) => s.clips[s.chosenIdx]?.clip_id).filter(Boolean) as string[]
        const ttsFilenames = readySegs.map((s) => s.ttsFilename ?? '')
        const blob = await exportApi.downloadProject({ clip_ids: clipIds, project_name: projectName, include_audio: true, tts_filenames: ttsFilenames })
        triggerDownload(blob as unknown as Blob, `${projectName}.zip`)
      } else {
        const segs: MergedSegment[] = readySegs
          .map((s) => ({ clip_id: s.clips[s.chosenIdx]?.clip_id ?? '', tts_filename: s.ttsFilename ?? undefined, copy_text: s.text }))
          .filter((s) => s.clip_id)
        const blob = await exportApi.downloadMerged({ segments: segs, project_name: projectName })
        triggerDownload(blob as unknown as Blob, `${projectName}.mp4`)
      }
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setExportError(detail || '导出失败，请重试。')
    } finally {
      setExporting(false)
    }
  }

  function triggerDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename; a.click()
    URL.revokeObjectURL(url)
  }

  const toggleVideo = (id: string) =>
    setSelectedVideoIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])

  // ── JSX
  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <ExportSidebar
        segments={segments}
        exportMode={exportMode}
        setExportMode={setExportMode}
        exporting={exporting}
        exportError={exportError}
        onExport={handleExport}
      />

      {/* main content, padded right to clear the fixed sidebar */}
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
              <p className="text-sm text-slate-300">暂无可匹配素材，请先在<Link href="/process" className="mx-1 text-indigo-400 hover:underline">素材处理</Link>完成视频处理。</p>
            </div>
          )}

          {doneVideos.length > 0 && (
            <section className="space-y-2">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
                限定视频范围<span className="normal-case font-normal text-slate-600 ml-1">（不选 = 全部）</span>
              </p>
              <div className="flex flex-wrap gap-2">
                {doneVideos.map((v) => (
                  <button key={v.id} onClick={() => toggleVideo(v.id)}
                    className={`px-3 py-1.5 rounded-lg border text-xs flex items-center gap-1.5 transition-colors ${
                      selectedVideoIds.includes(v.id)
                        ? 'border-indigo-500 bg-indigo-500/15 text-indigo-300'
                        : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-500'
                    }`}
                  >
                    <Film className="w-3 h-3" />{v.name}
                  </button>
                ))}
              </div>
            </section>
          )}

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

          <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
              <SplitSquareHorizontal className="w-4 h-4 text-slate-500" />批量拆分文案
            </p>
            <textarea
              value={globalQuery}
              onChange={(e) => setGlobalQuery(e.target.value)}
              placeholder="粘贴完整文案，按空行自动拆分为多段分别匹配..."
              rows={4}
              className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm outline-none focus:border-indigo-500 placeholder-slate-600 resize-none"
            />
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
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
                  文案段落 · {segments.length} 段
                </p>
                <button onClick={() => setSegments([])} className="text-xs text-slate-600 hover:text-red-400 transition-colors">清空全部</button>
              </div>
              {segments.map((seg, i) => (
                <SegmentRow
                  key={seg.id}
                  seg={seg} index={i}
                  onTextChange={(t) => patchSeg(seg.id, { text: t })}
                  onRemove={() => removeSegment(seg.id)}
                  onMatch={() => matchSegment(seg.id)}
                  onChoose={(ci) => patchSeg(seg.id, { chosenIdx: ci })}
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

        </div>
      </div>

      {previewClip && <PreviewModal clip={previewClip} onClose={() => setPreviewClip(null)} />}
    </main>
  )
}
