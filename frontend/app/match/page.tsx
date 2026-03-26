'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import {
  AlertCircle, ArrowLeft, CheckCircle2, ChevronDown, ChevronUp,
  Film, Loader2, Mic, MicOff, Play,
  Plus, Search, Sparkles, SplitSquareHorizontal, Trash2, Volume2, X
} from 'lucide-react'
import apiClient, { exportApi, ttsApi, type MatchClip, type MergedSegment, type Video } from '@/lib/api'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const clipStreamUrl = (id: string) => `${API_BASE}/api/videos/clips/${id}/stream`
const audioSrc = (f: string) => `${API_BASE}/api/tts/audio/${f}`

function fmt(s: number) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

interface Segment {
  id: string
  text: string
  clips: MatchClip[]
  chosenIdx: number
  ttsFilename: string | null
  ttsLoading: boolean
  ttsError: string
  matchLoading: boolean
  matchError: string
  expanded: boolean
}

type ExportMode = 'zip' | 'merged'

// ── ScoreBar ──────────────────────────────────────────────────────────────────
function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, (score / 10) * 100))
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 rounded-full bg-slate-800 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[10px] tabular-nums text-slate-500 w-6 text-right">{score.toFixed(1)}</span>
    </div>
  )
}

// ── ClipCard ──────────────────────────────────────────────────────────────────
function ClipCard({
  clip, chosen, onChoose, onPreview,
}: {
  clip: MatchClip; chosen: boolean; onChoose: () => void; onPreview: () => void
}) {
  const name = clip.clip_path.split(/[\/]/).pop() ?? clip.clip_path
  return (
    <div
      onClick={onChoose}
      className={`relative flex-shrink-0 w-52 rounded-xl border cursor-pointer select-none transition-all ${
        chosen
          ? 'border-indigo-500 bg-indigo-500/10 ring-1 ring-indigo-500/40'
          : 'border-slate-700 bg-slate-900/50 hover:border-slate-500'
      }`}
    >
      {chosen && (
        <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-indigo-500 flex items-center justify-center z-10">
          <CheckCircle2 className="w-3.5 h-3.5 text-white" />
        </div>
      )}
      <div className="w-full h-24 rounded-t-xl bg-slate-800 flex items-center justify-center">
        <button
          onClick={(e) => { e.stopPropagation(); onPreview() }}
          className="w-9 h-9 rounded-full bg-black/50 hover:bg-black/70 flex items-center justify-center transition-colors"
        >
          <Play className="w-4 h-4 text-white ml-0.5" />
        </button>
      </div>
      <div className="px-3 py-2.5 space-y-1.5">
        <p className="text-xs text-slate-200 font-medium truncate">{name}</p>
        <p className="text-[10px] text-slate-500">{fmt(clip.start_time)} – {fmt(clip.end_time)} · {clip.duration.toFixed(1)}s</p>
        <ScoreBar score={clip.score} />
        {clip.reason && (
          <p className="text-[10px] text-slate-400 leading-snug line-clamp-2 italic">{clip.reason}</p>
        )}
      </div>
    </div>
  )
}

// ── PreviewModal ──────────────────────────────────────────────────────────────
function PreviewModal({ clip, onClose }: { clip: MatchClip; onClose: () => void }) {
  const [err, setErr] = useState(false)
  const name = clip.clip_path.split(/[\/]/).pop() ?? clip.clip_path
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="relative w-full max-w-3xl mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <p className="text-slate-100 font-medium truncate max-w-[80%]">
            {name}
            <span className="ml-2 text-xs text-slate-400 font-normal">{fmt(clip.start_time)} – {fmt(clip.end_time)}</span>
          </p>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="rounded-xl overflow-hidden bg-black ring-1 ring-slate-700 min-h-[120px] flex items-center justify-center">
          {err ? (
            <p className="text-slate-400 text-sm px-8 py-10">该片段格式浏览器不支持直接预览。</p>
          ) : (
            <video
              key={clip.clip_id}
              src={clipStreamUrl(clip.clip_id)}
              controls autoPlay
              className="w-full max-h-[65vh] object-contain"
              onError={() => setErr(true)}
            >
              <track kind="captions" srcLang="zh" label="中文字幕" />
            </video>
          )}
        </div>
      </div>
    </div>
  )
}

// ── SegmentRow ────────────────────────────────────────────────────────────────
function SegmentRow({
  seg, index, onTextChange, onRemove, onMatch, onChoose,
  onTts, onPlayAudio, onStopAudio, playingAudio, onPreview, onToggleExpand,
}: {
  seg: Segment; index: number
  onTextChange: (t: string) => void
  onRemove: () => void
  onMatch: () => void
  onChoose: (idx: number) => void
  onTts: () => void
  onPlayAudio: () => void
  onStopAudio: () => void
  playingAudio: boolean
  onPreview: (clip: MatchClip) => void
  onToggleExpand: () => void
}) {
  const chosen = seg.clips[seg.chosenIdx] ?? null
  return (
    <div className="rounded-2xl border border-slate-800 bg-[#0e1017] overflow-hidden">
      {/* header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-slate-900/60 border-b border-slate-800">
        <div className="w-6 h-6 rounded-lg bg-indigo-500/20 text-indigo-300 text-xs font-bold flex items-center justify-center shrink-0">
          {index + 1}
        </div>
        <span className="text-xs text-slate-400 font-medium">段落 {index + 1}</span>
        <div className="flex-1" />
        {chosen && <span className="text-[10px] text-emerald-500 bg-emerald-500/10 border border-emerald-500/20 rounded-full px-2 py-0.5">已选片段</span>}
        {seg.ttsFilename && <span className="text-[10px] text-violet-400 bg-violet-500/10 border border-violet-500/20 rounded-full px-2 py-0.5">配音就绪</span>}
        <button onClick={onToggleExpand} className="text-slate-600 hover:text-slate-300 transition-colors">
          {seg.expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        <button onClick={onRemove} className="text-slate-700 hover:text-red-400 transition-colors">
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      <div className="px-4 py-4 space-y-4">
        {/* text + match */}
        <div className="flex gap-2">
          <textarea
            value={seg.text}
            onChange={(e) => onTextChange(e.target.value)}
            placeholder="输入该段文案..."
            rows={2}
            className="flex-1 rounded-xl bg-slate-900/60 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 resize-none placeholder-slate-600"
          />
          <button
            onClick={onMatch}
            disabled={!seg.text.trim() || seg.matchLoading}
            className="shrink-0 px-3 py-2 h-fit rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-sm font-medium flex items-center gap-1.5 mt-0.5 transition-colors"
          >
            {seg.matchLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            {seg.matchLoading ? '匹配中' : '匹配'}
          </button>
        </div>
        {seg.matchError && <p className="text-xs text-red-400">{seg.matchError}</p>}

        {/* candidates */}
        {seg.clips.length > 0 && (
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-2.5">
              候选视频 · {seg.clips.length} 个
              <span className="normal-case font-normal ml-1 text-slate-600">— 点击选择</span>
            </p>
            <div className="flex gap-3 overflow-x-auto pb-2">
              {seg.clips.map((clip, ci) => (
                <ClipCard
                  key={clip.clip_id} clip={clip}
                  chosen={seg.chosenIdx === ci}
                  onChoose={() => onChoose(ci)}
                  onPreview={() => onPreview(clip)}
                />
              ))}
            </div>
          </div>
        )}

        {/* TTS bar */}
        {chosen && (
          <div className="flex items-center gap-3 rounded-xl bg-slate-900/40 border border-slate-800 px-3 py-2.5">
            <Volume2 className="w-4 h-4 text-slate-500 shrink-0" />
            <div className="flex-1 min-w-0">
              {seg.ttsError && !seg.ttsFilename
                ? <p className="text-xs text-red-400 truncate">{seg.ttsError}</p>
                : seg.ttsFilename
                  ? <p className="text-xs text-emerald-400 font-medium">✓ 配音已合成</p>
                  : <p className="text-xs text-slate-500">尚未合成配音</p>
              }
            </div>
            {seg.ttsFilename && (
              playingAudio
                ? <button onClick={onStopAudio} className="shrink-0 px-2.5 py-1 rounded-lg bg-violet-500/20 text-violet-300 text-xs flex items-center gap-1 hover:bg-violet-500/30 transition-colors"><MicOff className="w-3.5 h-3.5" /> 停止</button>
                : <button onClick={onPlayAudio} className="shrink-0 px-2.5 py-1 rounded-lg bg-slate-800 text-slate-300 text-xs flex items-center gap-1 hover:bg-slate-700 transition-colors"><Play className="w-3.5 h-3.5" /> 试听</button>
            )}
            <button
              onClick={onTts}
              disabled={seg.ttsLoading || !seg.text.trim()}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:bg-slate-800 disabled:text-slate-600 text-xs text-white font-medium flex items-center gap-1.5 transition-colors"
            >
              {seg.ttsLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Mic className="w-3.5 h-3.5" />}
              {seg.ttsLoading ? '合成中' : seg.ttsFilename ? '重新合成' : '合成配音'}
            </button>
          </div>
        )}

        {/* expanded detail */}
        {seg.expanded && chosen && (chosen.asr_text || chosen.vlm_description) && (
          <div className="rounded-xl bg-slate-900/30 border border-slate-800 px-3 py-3 space-y-2">
            {chosen.asr_text && (
              <div><p className="text-[10px] text-slate-600 uppercase tracking-widest mb-1">台词</p><p className="text-xs text-slate-300 leading-relaxed">{chosen.asr_text}</p></div>
            )}
            {chosen.vlm_description && (
              <div><p className="text-[10px] text-slate-600 uppercase tracking-widest mb-1">画面描述</p><p className="text-xs text-slate-300 leading-relaxed">{chosen.vlm_description}</p></div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
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
    apiClient.get<unknown, Video[]>('/api/videos')
      .then((d) => setVideos(d || []))
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

  // split global query into segments by blank lines or newlines
  function splitGlobalQuery() {
    if (!globalQuery.trim()) return
    const parts = globalQuery
      .split(/\n{2}|。(?=\S)/)
      .map((p) => p.trim())
      .filter(Boolean)
    const newId = (i: number) => `seg-${counter + i}`
    setCounter((c) => c + parts.length)
    setSegments(parts.map((text, i) => makeSeg(newId(i), text)))
  }

  async function matchSegment(id: string) {
    const seg = segments.find((s) => s.id === id)
    if (!seg || !seg.text.trim()) return
    patchSeg(id, { matchLoading: true, matchError: '' })
    try {
      const data = await apiClient.post<unknown, { recommended: MatchClip[]; candidates: MatchClip[] }>('/api/match', {
        query: seg.text.trim(),
        top_k: topK,
        top_n: topN,
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
        const blob = await exportApi.downloadProject({
          clip_ids: clipIds,
          project_name: projectName,
          include_audio: true,
          tts_filenames: ttsFilenames,
        })
        triggerDownload(blob as unknown as Blob, `${projectName}.zip`)
      } else {
        const segs: MergedSegment[] = readySegs.map((s) => ({
          clip_id: s.clips[s.chosenIdx]?.clip_id ?? '',
          tts_filename: s.ttsFilename ?? undefined,
          copy_text: s.text,
        })).filter((s) => s.clip_id)
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

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <div className="max-w-4xl mx-auto px-6 py-10 space-y-8">

        {/* breadcrumb */}
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
            <p className="text-sm text-slate-300">暂无可匹配素材，请先在
              <Link href="/process" className="mx-1 text-indigo-400 hover:underline">处理管线</Link>
              完成视频处理。
            </p>
          </div>
        )}

        {/* video scope */}
        {doneVideos.length > 0 && (
          <section className="space-y-2">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
              限定视频范围 <span className="normal-case font-normal text-slate-600">（不选 = 全部）</span>
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

        {/* params row */}
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

        {/* global query splitter */}
        <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
            <SplitSquareHorizontal className="w-4 h-4 text-slate-500" />批量拆分文案
          </p>
          <textarea
            value={globalQuery}
            onChange={(e) => setGlobalQuery(e.target.value)}
            placeholder="粘贴完整文案，系统将按段落自动拆分成多个段落分别匹配..."
            rows={4}
            className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm outline-none focus:border-indigo-500 placeholder-slate-600 resize-none"
          />
          <div className="flex items-center gap-3">
            <button
              onClick={splitGlobalQuery}
              disabled={!globalQuery.trim()}
              className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-sm flex items-center gap-2 border border-slate-700 transition-colors"
            >
              <SplitSquareHorizontal className="w-4 h-4" />拆分为段落
            </button>
            {segments.length > 0 && (
              <button
                onClick={matchAll}
                disabled={globalMatching}
                className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm flex items-center gap-2 transition-colors"
              >
                {globalMatching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                {globalMatching ? '全部匹配中...' : '全部匹配'}
              </button>
            )}
            <button
              onClick={() => addSegment()}
              className="ml-auto px-3 py-2 rounded-xl border border-slate-700 bg-slate-800/40 hover:border-slate-500 text-xs text-slate-400 flex items-center gap-1.5 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />手动添加段落
            </button>
          </div>
        </section>

        {/* segment list */}
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

        {/* export panel */}
        {readySegs.length > 0 && (
          <section className="rounded-2xl border border-slate-700 bg-slate-900/40 p-5 space-y-4">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">导出成片</p>

            {/* mode selector */}
            <div className="flex gap-2">
              <button
                onClick={() => setExportMode('zip')}
                className={`flex-1 py-2.5 rounded-xl border text-sm font-medium transition-colors flex items-center justify-center gap-2 ${
                  exportMode === 'zip'
                    ? 'border-indigo-500 bg-indigo-500/10 text-indigo-300'
                    : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-500'
                }`}
              >
                <span className="text-base">📦</span> 素材压缩包
              </button>
              <button
                onClick={() => setExportMode('merged')}
                className={`flex-1 py-2.5 rounded-xl border text-sm font-medium transition-colors flex items-center justify-center gap-2 ${
                  exportMode === 'merged'
                    ? 'border-violet-500 bg-violet-500/10 text-violet-300'
                    : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-500'
                }`}
              >
                <span className="text-base">🎬</span> 完整带配音视频
              </button>
            </div>

            <p className="text-xs text-slate-500">
              {exportMode === 'zip'
                ? `将导出 ${readySegs.length} 个视频片段 + 已合成的配音音频，打包为 ZIP。`
                : `将用 ffmpeg 把每段配音合入视频，再拼接为完整 MP4。需服务器已安装 ffmpeg。`}
            </p>

            {exportError && (
              <p className="text-xs text-red-400">{exportError}</p>
            )}

            <button
              onClick={handleExport}
              disabled={exporting}
              className={`w-full py-3 rounded-xl font-medium text-sm flex items-center justify-center gap-2 transition-colors ${
                exportMode === 'zip'
                  ? 'bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600'
                  : 'bg-violet-600 hover:bg-violet-500 disabled:bg-slate-800 disabled:text-slate-600'
              }`}
            >
              {exporting
                ? <><Loader2 className="w-4 h-4 animate-spin" />导出中，请稍候...</>
                : exportMode === 'zip'
                  ? <><span>📦</span> 下载素材压缩包（{readySegs.length} 段）</>
                  : <><span>🎬</span> 导出带配音成片（{readySegs.length} 段）</>
              }
            </button>
          </section>
        )}

      </div>

      {previewClip && <PreviewModal clip={previewClip} onClose={() => setPreviewClip(null)} />}
    </main>
  )
}
