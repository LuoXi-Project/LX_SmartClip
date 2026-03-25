'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { AlertCircle, ArrowLeft, ChevronDown, ChevronUp, Download, Film, Loader2, Play, Search, Sparkles, X } from 'lucide-react'
import apiClient, { exportApi, type MatchClip, type MatchResponse, type Video } from '@/lib/api'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function ResultCard({
  clip,
  index,
  expanded,
  onToggle,
  selected,
  onSelect,
  onPreview,
}: {
  clip: MatchClip
  index: number
  expanded: boolean
  onToggle: () => void
  selected: boolean
  onSelect: (checked: boolean) => void
  onPreview: () => void
}) {
  const name = clip.clip_path.split(/[\\/]/).pop() ?? clip.clip_path

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 overflow-hidden">
      <div className="px-4 py-3 flex items-start gap-3">
        <div className="mt-0.5 shrink-0">
          <input
            type="checkbox"
            checked={selected}
            aria-label={`选择片段 ${index + 1}`}
            onChange={(e) => onSelect(e.target.checked)}
            className="w-4 h-4 rounded border-slate-600 bg-slate-800 text-indigo-500 focus:ring-indigo-500"
          />
        </div>

        <div className="w-7 h-7 rounded-lg bg-indigo-500/20 text-indigo-300 text-xs font-bold flex items-center justify-center shrink-0">
          {index + 1}
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-200 truncate">{name}</p>
          <p className="text-xs text-slate-500 mt-1">
            {formatTime(clip.start_time)} - {formatTime(clip.end_time)} · {clip.duration.toFixed(1)}s · 评分 {clip.score.toFixed(1)}
          </p>
          {clip.reason && <p className="text-xs text-slate-400 mt-2 italic">{clip.reason}</p>}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onPreview}
            className="text-xs px-2 py-1 rounded-md border border-slate-700 text-slate-300 hover:border-slate-500 transition-colors flex items-center gap-1"
          >
            <Play className="w-3 h-3" />预览
          </button>
          <button onClick={onToggle} className="text-slate-500 hover:text-slate-300 transition-colors">
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-slate-800 px-4 py-3 space-y-2">
          {clip.asr_text && (
            <div>
              <p className="text-xs text-slate-500 mb-1">台词</p>
              <p className="text-sm text-slate-300 leading-relaxed">{clip.asr_text}</p>
            </div>
          )}
          {clip.vlm_description && (
            <div>
              <p className="text-xs text-slate-500 mb-1">画面描述</p>
              <p className="text-sm text-slate-300 leading-relaxed">{clip.vlm_description}</p>
            </div>
          )}
          {!clip.asr_text && !clip.vlm_description && <p className="text-xs text-slate-600">该片段暂无描述内容</p>}
        </div>
      )}
    </div>
  )
}

export default function MatchPage() {
  const [videos, setVideos] = useState<Video[]>([])
  const [selectedVideoIds, setSelectedVideoIds] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(12)
  const [topN, setTopN] = useState(5)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<MatchResponse | null>(null)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [showAllCandidates, setShowAllCandidates] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [selectedClipIds, setSelectedClipIds] = useState<Set<string>>(new Set())
  const [previewClip, setPreviewClip] = useState<MatchClip | null>(null)
  const [previewError, setPreviewError] = useState(false)

  useEffect(() => {
    apiClient
      .get<unknown, Video[]>('/api/videos')
      .then((data) => setVideos(data || []))
      .catch(console.error)
  }, [])

  const doneVideos = videos.filter((v) => v.status === 'done' && v.total_clips > 0)

  const toggleVideo = (id: string) => {
    setSelectedVideoIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const toggleExpanded = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleMatch = async () => {
    if (!query.trim() || loading) return

    setLoading(true)
    setError('')
    setResult(null)
    setExpandedIds(new Set())
    setShowAllCandidates(false)
    setSelectedClipIds(new Set())
    setPreviewClip(null)
    setPreviewError(false)

    try {
      const data = await apiClient.post<unknown, MatchResponse>('/api/match', {
        query: query.trim(),
        top_k: topK,
        top_n: topN,
        video_ids: selectedVideoIds.length > 0 ? selectedVideoIds : null,
      })
      setResult(data)
      setSelectedClipIds(new Set())
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || '匹配失败，请检查服务配置。')
    } finally {
      setLoading(false)
    }
  }

  const displayList = showAllCandidates ? result?.candidates || [] : result?.recommended || []
  const exportCount = selectedClipIds.size

  const toggleClipSelection = (clipId: string, checked: boolean) => {
    setSelectedClipIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(clipId)
      else next.delete(clipId)
      return next
    })
  }

  const toggleSelectAllInView = (checked: boolean) => {
    setSelectedClipIds((prev) => {
      const next = new Set(prev)
      for (const clip of displayList) {
        if (checked) next.add(clip.clip_id)
        else next.delete(clip.clip_id)
      }
      return next
    })
  }

  const openPreview = (clip: MatchClip) => {
    setPreviewError(false)
    setPreviewClip(clip)
  }

  const closePreview = () => {
    setPreviewClip(null)
    setPreviewError(false)
  }

  const handleExport = async () => {
    if (!result || exporting || selectedClipIds.size === 0) return
    setExporting(true)
    try {
      const clipIds = Array.from(selectedClipIds)
      const projectName = query.trim().slice(0, 30).replace(/\s+/g, '_') || 'smartclip_project'
      const blob = await exportApi.downloadProject({ clip_ids: clipIds, project_name: projectName })
      const url = URL.createObjectURL(blob as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${projectName}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('导出失败，请重试。')
    } finally {
      setExporting(false)
    }
  }

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <div className="max-w-4xl mx-auto px-6 py-10 space-y-8">
        <div className="flex items-center gap-3">
          <Link href="/process" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
            <ArrowLeft className="w-4 h-4" />处理管线
          </Link>
          <div className="w-px h-4 bg-slate-700" />
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-indigo-400" />文案匹配
          </h1>
        </div>

        <section className="space-y-3">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">输入文案</label>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入或粘贴文案，系统会返回最匹配的视频片段..."
            rows={5}
            className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm outline-none focus:border-indigo-500"
          />

          <div className="flex flex-wrap items-center gap-4">
            <label className="text-xs text-slate-500 flex items-center gap-2">
              初筛数量
              <input
                type="number"
                min={1}
                max={50}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className="w-16 rounded-lg bg-slate-800 border border-slate-700 px-2 py-1 text-center text-slate-200"
              />
            </label>

            <label className="text-xs text-slate-500 flex items-center gap-2">
              推荐数量
              <input
                type="number"
                min={1}
                max={20}
                value={topN}
                onChange={(e) => setTopN(Number(e.target.value))}
                className="w-16 rounded-lg bg-slate-800 border border-slate-700 px-2 py-1 text-center text-slate-200"
              />
            </label>

            <button
              onClick={handleMatch}
              disabled={!query.trim() || loading}
              className="ml-auto px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-sm font-medium flex items-center gap-2"
            >
              {loading ? <><Loader2 className="w-4 h-4 animate-spin" />匹配中...</> : <><Search className="w-4 h-4" />开始匹配</>}
            </button>
          </div>
        </section>

        {doneVideos.length > 0 && (
          <section className="space-y-2">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
              限定视频范围 <span className="normal-case font-normal text-slate-600">（不选 = 全部）</span>
            </p>
            <div className="flex flex-wrap gap-2">
              {doneVideos.map((v) => (
                <button
                  key={v.id}
                  onClick={() => toggleVideo(v.id)}
                  className={`px-3 py-1.5 rounded-lg border text-xs flex items-center gap-1.5 ${
                    selectedVideoIds.includes(v.id)
                      ? 'border-indigo-500 bg-indigo-500/15 text-indigo-300'
                      : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-500'
                  }`}
                >
                  <Film className="w-3 h-3" />
                  {v.name}
                </button>
              ))}
            </div>
          </section>
        )}

        {doneVideos.length === 0 && (
          <div className="rounded-xl border border-amber-600/30 bg-amber-500/5 px-5 py-4 flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-amber-400" />
            <p className="text-sm text-slate-300">
              暂无可匹配素材，请先在
              <Link href="/process" className="mx-1 text-indigo-400 hover:underline">处理管线</Link>
              完成视频处理。
            </p>
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-red-600/30 bg-red-500/5 px-5 py-4 text-sm text-red-300">
            {error}
          </div>
        )}

        {result && (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
                {showAllCandidates ? '初筛候选' : '推荐片段'}
                <span className="ml-2 normal-case font-normal text-slate-600">共 {displayList.length} 个</span>
              </h2>

              <div className="flex items-center gap-3">
                {displayList.length > 0 && (
                  <label className="text-xs text-slate-400 flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={displayList.every((c) => selectedClipIds.has(c.clip_id))}
                      aria-label="当前列表全选"
                      onChange={(e) => toggleSelectAllInView(e.target.checked)}
                      className="w-3.5 h-3.5 rounded border-slate-600 bg-slate-800 text-indigo-500 focus:ring-indigo-500"
                    />
                    当前列表全选
                  </label>
                )}
                {result.candidates.length > result.recommended.length && (
                  <button
                    onClick={() => setShowAllCandidates((v) => !v)}
                    className="text-xs text-slate-500 hover:text-slate-300"
                  >
                    {showAllCandidates ? '只看推荐' : '查看全部候选'}
                  </button>
                )}
                {result.recommended.length > 0 && (
                  <button
                    onClick={handleExport}
                    disabled={exporting || exportCount === 0}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/40 hover:border-slate-500 text-xs text-slate-300 disabled:opacity-50 transition-colors"
                  >
                    {exporting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
                    {exporting ? '导出中...' : `导出工程包（已选 ${exportCount}）`}
                  </button>
                )}
              </div>
            </div>

            {displayList.length === 0 ? (
              <div className="rounded-xl border border-slate-800 px-5 py-8 text-center text-sm text-slate-500">
                未找到匹配片段，请确认已完成向量入库。
              </div>
            ) : (
              <div className="space-y-2">
                {displayList.map((clip, i) => (
                  <ResultCard
                    key={clip.clip_id}
                    clip={clip}
                    index={i}
                    expanded={expandedIds.has(clip.clip_id)}
                    onToggle={() => toggleExpanded(clip.clip_id)}
                    selected={selectedClipIds.has(clip.clip_id)}
                    onSelect={(checked) => toggleClipSelection(clip.clip_id, checked)}
                    onPreview={() => openPreview(clip)}
                  />
                ))}
              </div>
            )}
          </section>
        )}
      </div>

      {previewClip && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={closePreview}
        >
          <div
            className="relative w-full max-w-4xl mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-slate-100 font-semibold truncate max-w-[85%]">
                {previewClip.clip_path.split(/[\\/]/).pop() ?? previewClip.clip_path}
                <span className="ml-2 text-xs text-slate-400 font-normal">
                  {formatTime(previewClip.start_time)} - {formatTime(previewClip.end_time)}
                </span>
              </h3>
              <button
                onClick={closePreview}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="rounded-xl overflow-hidden bg-black shadow-2xl ring-1 ring-slate-700 min-h-[120px] flex items-center justify-center">
              {previewError ? (
                <p className="text-slate-400 text-sm text-center px-8 py-10">
                  该片段格式浏览器不支持直接预览。
                </p>
              ) : (
                <video
                  key={previewClip.clip_id}
                  src={`${API_BASE_URL}/api/videos/clips/${previewClip.clip_id}/stream`}
                  controls
                  autoPlay
                  className="w-full max-h-[70vh] object-contain"
                  onError={() => setPreviewError(true)}
                >
                  <track kind="captions" srcLang="zh" label="中文字幕" />
                </video>
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
