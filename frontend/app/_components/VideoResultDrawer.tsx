'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { X, Loader2, Save, Search, Check, Film, Subtitles, ListTree, Play, Trash2, Plus, RotateCcw } from 'lucide-react'
import { API_BASE_URL, clipsApi, processJobsApi, type AsrSegmentJson, type ClipResult } from '@/lib/api'
import { videoStreamUrl, clipStreamUrl, fmt } from '@/app/match/_components/types'
import { useToast } from '@/components/ui/toast-provider'

type VideoOption = { id: string; name: string }

export type VideoResultDrawerProps = {
  open: boolean
  onClose: () => void
  /** 优先展示的视频 */
  videoId?: string
  /** 可选：让用户在抽屉内切换视频 */
  videoOptions?: VideoOption[]
  title?: string
}

type EditState = {
  asr_text: string
  /** 句级时间轴；与库中 JSON 同步，未改动句级时保存不带上 asr_segments 以免误清空 */
  asr_segments: AsrSegmentJson[]
  asrSegmentsDirty: boolean
  vlm_description: string
  dirty: boolean
  saving: boolean
  error: string
}

function parseAsrSegments(raw: string | null | undefined): AsrSegmentJson[] {
  if (!raw || !String(raw).trim()) return []
  try {
    const data = JSON.parse(String(raw)) as unknown
    if (!Array.isArray(data)) return []
    return data.map((item) => {
      const x = item as Record<string, unknown>
      const start = typeof x.start === 'number' ? x.start : Number(x.start)
      const end = typeof x.end === 'number' ? x.end : Number(x.end)
      const text = typeof x.text === 'string' ? x.text : String(x.text ?? '')
      return {
        start: Number.isFinite(start) ? start : 0,
        end: Number.isFinite(end) ? end : 0,
        text,
      }
    })
  } catch {
    return []
  }
}

function joinSegmentsText(segs: AsrSegmentJson[]): string {
  return segs.map((s) => s.text ?? '').join('')
}

function validateAsrSegments(segs: AsrSegmentJson[], durationSec: number): string | null {
  const max = durationSec > 0 ? durationSec : Number.POSITIVE_INFINITY
  for (let i = 0; i < segs.length; i++) {
    const { start, end } = segs[i]
    if (start < 0) return `第 ${i + 1} 句：开始时间不能为负`
    if (!(start < end)) return `第 ${i + 1} 句：开始须小于结束`
    if (end > max + 0.05) return `第 ${i + 1} 句：结束时间超过本片段时长（约 ${durationSec.toFixed(2)}s）`
  }
  return null
}

function safeStr(v: string | null | undefined) {
  return (v ?? '').toString()
}

function apiDetailMessage(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  if (d != null && typeof d === 'object') {
    try {
      return JSON.stringify(d)
    } catch {
      return '请求失败'
    }
  }
  return '请求失败'
}

export function VideoResultDrawer({
  open,
  onClose,
  videoId,
  videoOptions,
  title = '处理结果',
}: VideoResultDrawerProps) {
  const router = useRouter()
  const toast = useToast()
  const initialVideoId = useMemo(() => {
    const v = (videoId || '').trim()
    if (v) return v
    const first = videoOptions?.[0]?.id || ''
    return first
  }, [videoId, videoOptions])

  const [curVideoId, setCurVideoId] = useState(initialVideoId)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [clips, setClips] = useState<ClipResult[]>([])
  const [q, setQ] = useState('')
  const [activeClipId, setActiveClipId] = useState<string>('')
  const [playerMode, setPlayerMode] = useState<'video' | 'clip'>('video')
  const [resultsTab, setResultsTab] = useState<'preview' | 'details'>('details')
  const [asrPreviewMode, setAsrPreviewMode] = useState<'timeline' | 'plain'>('timeline')

  const [editing, setEditing] = useState<Record<string, EditState>>({})
  const [reprocessBusyId, setReprocessBusyId] = useState<string | null>(null)

  const videoRef = useRef<HTMLVideoElement | null>(null)

  useEffect(() => {
    if (!open) return
    setCurVideoId(initialVideoId)
  }, [open, initialVideoId])

  useEffect(() => {
    if (!open) return
    if (!curVideoId) return
    setLoading(true)
    setErr('')
    clipsApi
      .listByVideo(curVideoId)
      .then((rows) => {
        setClips(rows || [])
        // 初始化编辑缓存（避免首次点击编辑时闪烁）
        const map: Record<string, EditState> = {}
        ;(rows || []).forEach((c) => {
          map[c.id] = {
            asr_text: safeStr(c.asr_text),
            asr_segments: parseAsrSegments(c.asr_segments),
            asrSegmentsDirty: false,
            vlm_description: safeStr(c.vlm_description),
            dirty: false,
            saving: false,
            error: '',
          }
        })
        setEditing(map)
        const first = rows?.[0]?.id || ''
        setActiveClipId(first)
      })
      .catch((e: unknown) => {
        setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '加载失败')
      })
      .finally(() => setLoading(false))
  }, [open, curVideoId])

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase()
    if (!kw) return clips
    return clips.filter((c) => {
      const a = safeStr(c.asr_text).toLowerCase()
      const v = safeStr(c.vlm_description).toLowerCase()
      const stLocal = editing[c.id]
      const segs = stLocal?.asr_segments ?? parseAsrSegments(c.asr_segments)
      const segBlob = joinSegmentsText(segs).toLowerCase()
      return a.includes(kw) || v.includes(kw) || segBlob.includes(kw) || c.id.toLowerCase().includes(kw)
    })
  }, [clips, q, editing])

  const asrPreviewRows = useMemo(() => {
    return filtered.map((c) => {
      const st = editing[c.id]
      const segs = st?.asr_segments ?? parseAsrSegments(c.asr_segments)
      const hasSegments = segs.length > 0
      const text = hasSegments ? joinSegmentsText(segs) : safeStr(st?.asr_text ?? c.asr_text)
      return {
        id: c.id,
        start: c.start_time || 0,
        end: c.end_time || 0,
        clip: c,
        segs,
        hasSegments,
        text,
      }
    })
  }, [filtered, editing])

  const asrPreviewPlainText = useMemo(() => {
    return asrPreviewRows
      .map((r) => r.text)
      .filter((t) => !!t.trim())
      .join('\n')
  }, [asrPreviewRows])

  const activeClip = clips.find((c) => c.id === activeClipId) || null

  const seekTo = (t: number) => {
    const el = videoRef.current
    if (!el) return
    try {
      el.currentTime = Math.max(0, t)
      void el.play().catch(() => {})
    } catch {
      // ignore
    }
  }

  /** 句级 start/end 相对片段内时间；原片模式下叠加 clip 起点 */
  const seekToSegment = (clip: ClipResult, seg: AsrSegmentJson) => {
    const base = playerMode === 'video' ? clip.start_time || 0 : 0
    seekTo(base + Math.max(0, seg.start))
  }

  const jumpToClip = (clip: ClipResult) => {
    setActiveClipId(clip.id)
    if (playerMode === 'video') {
      seekTo(clip.start_time || 0)
    }
  }

  const setEditField = (clipId: string, field: 'asr_text' | 'vlm_description', value: string) => {
    setEditing((prev) => {
      const cur = prev[clipId] || {
        asr_text: '',
        asr_segments: [],
        asrSegmentsDirty: false,
        vlm_description: '',
        dirty: false,
        saving: false,
        error: '',
      }
      return {
        ...prev,
        [clipId]: {
          ...cur,
          [field]: value,
          dirty: true,
          error: '',
        },
      }
    })
  }

  const patchAsrSegments = (
    clipId: string,
    clip: ClipResult,
    updater: (prev: AsrSegmentJson[]) => AsrSegmentJson[],
  ) => {
    setEditing((prev) => {
      const cur = prev[clipId] || {
        asr_text: safeStr(clip.asr_text),
        asr_segments: parseAsrSegments(clip.asr_segments),
        asrSegmentsDirty: false,
        vlm_description: safeStr(clip.vlm_description),
        dirty: false,
        saving: false,
        error: '',
      }
      const nextSegs = updater(cur.asr_segments)
      const nextText = joinSegmentsText(nextSegs)
      return {
        ...prev,
        [clipId]: {
          ...cur,
          asr_segments: nextSegs,
          asrSegmentsDirty: true,
          asr_text: nextText,
          dirty: true,
          error: '',
        },
      }
    })
  }

  const saveClip = async (clipId: string) => {
    const st = editing[clipId]
    const clipRow = clips.find((c) => c.id === clipId)
    if (!st || st.saving) return
    if (clipRow) {
      const segErr = validateAsrSegments(st.asr_segments, clipRow.duration || 0)
      if (segErr) {
        setEditing((p) => ({ ...p, [clipId]: { ...p[clipId], error: segErr } }))
        return
      }
    }
    setEditing((p) => ({ ...p, [clipId]: { ...p[clipId], saving: true, error: '' } }))
    try {
      const payload: {
        asr_text: string
        vlm_description: string
        asr_segments?: string | null
      } = { asr_text: st.asr_text, vlm_description: st.vlm_description }
      if (st.asrSegmentsDirty) {
        payload.asr_segments = JSON.stringify(st.asr_segments)
      }
      await clipsApi.update(clipId, payload)
      setClips((prev) =>
        prev.map((c) =>
          c.id === clipId
            ? {
                ...c,
                asr_text: st.asr_text,
                vlm_description: st.vlm_description,
                ...(st.asrSegmentsDirty ? { asr_segments: payload.asr_segments ?? null } : {}),
              }
            : c
        )
      )
      setEditing((p) => ({
        ...p,
        [clipId]: { ...p[clipId], saving: false, dirty: false, asrSegmentsDirty: false, error: '' },
      }))
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '保存失败'
      setEditing((p) => ({ ...p, [clipId]: { ...p[clipId], saving: false, error: msg } }))
    }
  }

  const enqueueClipReprocess = async (
    clipId: string,
    preset: 'asr_only' | 'vlm_only' | 'asr_vlm' | 'embed_only',
    navigateToProcess: boolean,
  ) => {
    if (!curVideoId || reprocessBusyId) return
    const skip_steps =
      preset === 'asr_only'
        ? (['split', 'extract_frames', 'vlm'] as const)
        : preset === 'vlm_only'
          ? (['split', 'asr'] as const)
          : preset === 'embed_only'
            ? (['split', 'extract_frames', 'asr', 'vlm'] as const)
            : (['split'] as const)
    setReprocessBusyId(clipId)
    try {
      await processJobsApi.create(curVideoId, {
        skip_steps: [...skip_steps],
        clip_ids: [clipId],
      })
      if (navigateToProcess) {
        router.push(`/process?video=${encodeURIComponent(curVideoId)}`)
        onClose()
      } else {
        toast.success(
          '已创建重跑任务（已默认更新向量）。请到「素材处理」页查看进度；完成后可点击左侧列表刷新本页数据。',
        )
      }
    } catch (e: unknown) {
      toast.error(apiDetailMessage(e))
    } finally {
      setReprocessBusyId(null)
    }
  }

  if (!open) return null

  const playerSrc =
    playerMode === 'video'
      ? videoStreamUrl(curVideoId)
      : activeClipId
        ? clipStreamUrl(activeClipId)
        : ''

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="absolute right-0 top-0 h-full w-full max-w-[96vw] xl:max-w-[1800px] bg-[#0d0f14] border-l border-slate-800 shadow-2xl flex flex-col">
        <div className="px-5 py-4 border-b border-slate-800 flex items-center gap-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-slate-200 truncate">{title}</div>
            <div className="text-xs text-slate-500 truncate">
              {curVideoId ? `video_id: ${curVideoId}` : '未选择视频'}
              {playerMode === 'clip' && activeClip ? ` · clip: ${fmt(activeClip.start_time)}-${fmt(activeClip.end_time)}` : ''}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {videoOptions && videoOptions.length > 0 && (
              <select
                value={curVideoId}
                onChange={(e) => setCurVideoId(e.target.value)}
                className="max-w-[280px] px-2 py-1.5 rounded-md bg-slate-900/60 border border-slate-700 text-xs text-slate-200 outline-none focus:border-indigo-500"
              >
                {videoOptions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={onClose}
              className="p-2 rounded-lg border border-slate-800 bg-slate-900/40 hover:border-slate-600 transition-colors"
              aria-label="关闭"
            >
              <X className="w-4 h-4 text-slate-300" />
            </button>
          </div>
        </div>

        <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2">
          {/* Player */}
          <div className="border-b lg:border-b-0 lg:border-r border-slate-800 min-h-0 flex flex-col">
            <div className="px-5 py-3 flex items-center gap-2 border-b border-slate-800">
              <div className="inline-flex items-center gap-1 rounded-full bg-slate-900/70 border border-slate-700 px-1 py-1 text-xs">
                <button
                  onClick={() => setPlayerMode('video')}
                  className={`px-3 py-0.5 rounded-full transition-colors ${
                    playerMode === 'video' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Film className="inline w-3.5 h-3.5 mr-1" />
                  原片预览
                </button>
                <button
                  onClick={() => setPlayerMode('clip')}
                  className={`px-3 py-0.5 rounded-full transition-colors ${
                    playerMode === 'clip' ? 'bg-emerald-500 text-slate-900' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Subtitles className="inline w-3.5 h-3.5 mr-1" />
                  片段预览
                </button>
              </div>

              {activeClip && playerMode === 'video' && (
                <button
                  onClick={() => seekTo(activeClip.start_time || 0)}
                  className="ml-auto text-xs px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/40 text-slate-200 hover:border-slate-500 transition-colors"
                >
                  跳到当前片段起点（{fmt(activeClip.start_time || 0)}）
                </button>
              )}
            </div>

            <div className="p-5 flex-1 min-h-0">
              {!curVideoId ? (
                <div className="h-full flex items-center justify-center text-sm text-slate-500">请选择一个视频</div>
              ) : (
                <div className="h-full rounded-xl border border-slate-800 bg-black/40 overflow-hidden">
                  <video
                    ref={videoRef}
                    src={playerSrc}
                    controls
                    className="w-full h-full object-contain bg-black"
                    crossOrigin="anonymous"
                  />
                </div>
              )}
              <div className="text-[11px] text-slate-600 mt-3">
                播放源：{playerSrc ? playerSrc.replace(API_BASE_URL, '') : '-'}
              </div>
            </div>
          </div>

          {/* Results */}
          <div className="min-h-0 flex flex-col">
            <div className="px-5 py-3 border-b border-slate-800 flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="搜索 ASR / VLM ..."
                  className="w-full pl-9 pr-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500 transition-colors"
                />
              </div>
              <div className="text-xs text-slate-500 shrink-0">{filtered.length}/{clips.length}</div>
            </div>

            <div className="px-5 py-2.5 border-b border-slate-800 bg-slate-950/20">
              <div className="inline-flex items-center gap-1 rounded-full bg-slate-900/70 border border-slate-700 px-1 py-1 text-xs">
                <button
                  type="button"
                  onClick={() => setResultsTab('details')}
                  className={`px-3 py-0.5 rounded-full transition-colors ${
                    resultsTab === 'details' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  片段详情
                </button>
                <button
                  type="button"
                  onClick={() => setResultsTab('preview')}
                  className={`px-3 py-0.5 rounded-full transition-colors ${
                    resultsTab === 'preview' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  ASR 全文预览
                </button>
              </div>
            </div>

            <div className="flex-1 min-h-0 overflow-auto">
              {loading ? (
                <div className="p-6 text-sm text-slate-500 flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />加载中...
                </div>
              ) : err ? (
                <div className="p-6 text-sm text-red-400">{err}</div>
              ) : resultsTab === 'preview' ? (
                <div className="p-5 h-full flex flex-col gap-2 min-h-0">
                  <div className="flex items-center gap-2">
                    <div className="text-xs text-slate-300 font-medium">ASR 全文预览</div>
                    <div className="ml-auto inline-flex items-center gap-1 rounded-full bg-slate-900/70 border border-slate-700 px-1 py-1 text-[11px]">
                      <button
                        type="button"
                        onClick={() => setAsrPreviewMode('timeline')}
                        className={`px-2 py-0.5 rounded-full transition-colors ${
                          asrPreviewMode === 'timeline' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        时间轴
                      </button>
                      <button
                        type="button"
                        onClick={() => setAsrPreviewMode('plain')}
                        className={`px-2 py-0.5 rounded-full transition-colors ${
                          asrPreviewMode === 'plain' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        全文
                      </button>
                    </div>
                  </div>
                  {asrPreviewMode === 'timeline' ? (
                    <div className="flex-1 min-h-0 overflow-auto rounded-lg border border-slate-800 bg-slate-900/30 divide-y divide-slate-800">
                      {asrPreviewRows.length === 0 ? (
                        <div className="px-3 py-2 text-[11px] text-slate-500">暂无可预览内容</div>
                      ) : (
                        asrPreviewRows.map((row) => (
                          <div key={row.id} className="px-3 py-2">
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => {
                                  setActiveClipId(row.id)
                                  jumpToClip(row.clip)
                                }}
                                className="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-300 hover:border-cyan-600/60"
                              >
                                {fmt(row.start)}-{fmt(row.end)}
                              </button>
                              <span className="text-[10px] text-slate-600 truncate">{row.id}</span>
                            </div>
                            {row.hasSegments ? (
                              <div className="mt-1.5 space-y-1">
                                {row.segs.map((seg, si) => {
                                  const absStart = Math.max(0, row.start + Math.max(0, seg.start))
                                  return (
                                    <button
                                      key={`${row.id}-${si}`}
                                      type="button"
                                      onClick={() => seekToSegment(row.clip, seg)}
                                      className="w-full text-left rounded border border-slate-800 bg-slate-950/40 px-2 py-1 hover:border-emerald-600/50 transition-colors"
                                    >
                                      <span className="text-[10px] text-emerald-300 mr-2">{fmt(absStart)}</span>
                                      <span className="text-[11px] text-slate-300">{seg.text || '（空）'}</span>
                                    </button>
                                  )
                                })}
                              </div>
                            ) : (
                              <p className="mt-1.5 text-[11px] leading-relaxed text-slate-300 whitespace-pre-wrap break-words">
                                {row.text || '（空）'}
                              </p>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  ) : (
                    <textarea
                      value={asrPreviewPlainText}
                      readOnly
                      className="w-full flex-1 min-h-0 h-full rounded-lg border border-slate-800 bg-slate-900/30 px-3 py-3 text-sm leading-7 text-slate-200 resize-none outline-none"
                      placeholder="暂无可预览内容"
                    />
                  )}
                  <div className="text-[10px] text-slate-500">
                    预览会实时展示当前编辑态（包括未保存改动）；点击时间点可在播放器快速定位。
                  </div>
                </div>
              ) : filtered.length === 0 ? (
                <div className="p-6 text-sm text-slate-500">没有匹配的片段</div>
              ) : (
                <div className="divide-y divide-slate-800">
                  {filtered.map((c) => {
                    const isActive = c.id === activeClipId
                    const st = editing[c.id]
                    const canSave = !!st?.dirty && !st?.saving
                    return (
                      <div
                        key={c.id}
                        className={`px-5 py-4 transition-colors ${isActive ? 'bg-indigo-500/5' : 'hover:bg-slate-900/30'}`}
                      >
                        <div className="flex items-start gap-3">
                          <button
                            onClick={() => jumpToClip(c)}
                            className={`shrink-0 mt-0.5 px-2 py-1 rounded-md border text-[11px] transition-colors ${
                              isActive ? 'border-indigo-500/50 text-indigo-300 bg-indigo-500/10' : 'border-slate-700 text-slate-400 hover:border-slate-500'
                            }`}
                          >
                            {fmt(c.start_time || 0)}-{fmt(c.end_time || 0)}
                          </button>
                          <div className="min-w-0 flex-1 space-y-2">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-xs text-slate-500 truncate max-w-[200px]">{c.id}</span>
                              <div className="ml-auto flex items-center gap-1.5 flex-wrap justify-end">
                                <button
                                  type="button"
                                  title="仅对本片段重新识别 ASR（不切分，默认同步入库向量）"
                                  disabled={!!reprocessBusyId || !curVideoId}
                                  onClick={() => void enqueueClipReprocess(c.id, 'asr_only', false)}
                                  className="text-xs px-2 py-1 rounded-md border border-slate-700 bg-slate-900/40 text-slate-300 hover:border-amber-600/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-0.5"
                                >
                                  {reprocessBusyId === c.id ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <RotateCcw className="w-3.5 h-3.5" />
                                  )}
                                  重跑 ASR+Embed
                                </button>
                                <button
                                  type="button"
                                  title="对本片段重跑 VLM + Embed（不切分，保证检索一致）"
                                  disabled={!!reprocessBusyId || !curVideoId}
                                  onClick={() => void enqueueClipReprocess(c.id, 'vlm_only', false)}
                                  className="text-xs px-2 py-1 rounded-md border border-slate-700 bg-slate-900/40 text-slate-300 hover:border-cyan-600/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-0.5"
                                >
                                  {reprocessBusyId === c.id ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <RotateCcw className="w-3.5 h-3.5" />
                                  )}
                                  重跑 VLM+Embed
                                </button>
                                <button
                                  type="button"
                                  title="本片段 ASR + VLM + Embed 重跑（不切分）"
                                  disabled={!!reprocessBusyId || !curVideoId}
                                  onClick={() => void enqueueClipReprocess(c.id, 'asr_vlm', false)}
                                  className="text-xs px-2 py-1 rounded-md border border-slate-700 bg-slate-900/40 text-slate-300 hover:border-indigo-600/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-0.5"
                                >
                                  {reprocessBusyId === c.id ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <RotateCcw className="w-3.5 h-3.5" />
                                  )}
                                  ASR+VLM+Embed
                                </button>
                                <button
                                  type="button"
                                  title="仅对本片段重跑 Embed（不切分）"
                                  disabled={!!reprocessBusyId || !curVideoId}
                                  onClick={() => void enqueueClipReprocess(c.id, 'embed_only', false)}
                                  className="text-xs px-2 py-1 rounded-md border border-slate-700 bg-slate-900/40 text-slate-300 hover:border-emerald-600/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-0.5"
                                >
                                  {reprocessBusyId === c.id ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <RotateCcw className="w-3.5 h-3.5" />
                                  )}
                                  重跑 Embed
                                </button>
                                
                                <button
                                  onClick={() => saveClip(c.id)}
                                  disabled={!canSave}
                                  className="text-xs px-2 py-1 rounded-md border border-slate-700 bg-slate-900/40 text-slate-300 hover:border-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                >
                                  {st?.saving ? <Loader2 className="inline w-3.5 h-3.5 mr-1 animate-spin" /> : <Save className="inline w-3.5 h-3.5 mr-1" />}
                                  保存
                                </button>
                              </div>
                            </div>

                            <div className="grid grid-cols-1 gap-2">
                              <div>
                                <div className="text-[11px] text-slate-500 mb-1">ASR（全文）</div>
                                <textarea
                                  value={st?.asr_text ?? safeStr(c.asr_text)}
                                  onChange={(e) => setEditField(c.id, 'asr_text', e.target.value)}
                                  rows={3}
                                  className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-800 text-xs text-slate-200 outline-none focus:border-indigo-500 transition-colors"
                                  placeholder="整段转写；修改下方句级时会按句拼接覆盖此处"
                                />
                              </div>

                              <div className="rounded-lg border border-slate-800/90 bg-slate-950/25 p-2.5 space-y-2">
                                <div className="flex flex-wrap items-center gap-2">
                                  <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
                                    <ListTree className="w-3.5 h-3.5 text-cyan-500/90 shrink-0" />
                                    <span>句级时间轴</span>
                                    <span className="text-slate-600">
                                      （起止秒，相对本片段；口播快剪等依赖此时间轴）
                                    </span>
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => {
                                      patchAsrSegments(c.id, c, (segs) => {
                                        const dur = c.duration || 0
                                        const last = segs[segs.length - 1]
                                        let start = last ? last.end : 0
                                        let end = last ? start + 1.5 : 1.5
                                        if (dur > 0) {
                                          if (start >= dur) start = Math.max(0, dur - 0.6)
                                          end = Math.min(Math.max(end, start + 0.4), dur)
                                        }
                                        return [...segs, { start, end, text: '' }]
                                      })
                                    }}
                                    className="ml-auto inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900/50 px-2 py-0.5 text-[11px] text-slate-300 hover:border-cyan-600/50 hover:text-cyan-200"
                                  >
                                    <Plus className="w-3 h-3" />
                                    添加一句
                                  </button>
                                </div>
                                {st &&
                                  st.asr_segments.length > 0 &&
                                  joinSegmentsText(st.asr_segments) !== st.asr_text && (
                                    <p className="text-[10px] leading-snug text-amber-400/85">
                                      全文与句级拼接不一致：若只改了上文全文，保存后句级不会自动跟着变；需要句级与成片时间对齐时请改下方或先改句级（会自动拼接全文）。
                                    </p>
                                  )}
                                {(!st?.asr_segments || st.asr_segments.length === 0) && (
                                  <p className="text-[11px] text-slate-600">
                                    暂无句级数据。运行视频 ASR 后会出现；也可点「添加一句」手写时间轴与字幕。
                                  </p>
                                )}
                                {st && st.asr_segments.length > 0 && (
                                  <div className="max-h-[220px] space-y-1.5 overflow-y-auto pr-0.5">
                                    {st.asr_segments.map((seg, si) => (
                                      <div
                                        key={si}
                                        className="flex flex-col gap-1 rounded-md border border-slate-800/80 bg-slate-900/40 p-2 sm:flex-row sm:items-start"
                                      >
                                        <div className="flex flex-wrap items-center gap-1.5 shrink-0 sm:w-[148px]">
                                          <input
                                            type="number"
                                            step={0.01}
                                            title="开始（秒）"
                                            value={Number.isFinite(seg.start) ? seg.start : 0}
                                            onChange={(e) => {
                                              const v = parseFloat(e.target.value)
                                              patchAsrSegments(c.id, c, (segs) => {
                                                const next = [...segs]
                                                next[si] = {
                                                  ...next[si],
                                                  start: Number.isFinite(v) ? v : 0,
                                                }
                                                return next
                                              })
                                            }}
                                            className="w-[68px] rounded border border-slate-700 bg-slate-950/60 px-1.5 py-0.5 text-[11px] text-slate-200"
                                          />
                                          <span className="text-slate-600">—</span>
                                          <input
                                            type="number"
                                            step={0.01}
                                            title="结束（秒）"
                                            value={Number.isFinite(seg.end) ? seg.end : 0}
                                            onChange={(e) => {
                                              const v = parseFloat(e.target.value)
                                              patchAsrSegments(c.id, c, (segs) => {
                                                const next = [...segs]
                                                next[si] = { ...next[si], end: Number.isFinite(v) ? v : 0 }
                                                return next
                                              })
                                            }}
                                            className="w-[68px] rounded border border-slate-700 bg-slate-950/60 px-1.5 py-0.5 text-[11px] text-slate-200"
                                          />
                                        </div>
                                        <input
                                          type="text"
                                          value={seg.text}
                                          onChange={(e) => {
                                            const v = e.target.value
                                            patchAsrSegments(c.id, c, (segs) => {
                                              const next = [...segs]
                                              next[si] = { ...next[si], text: v }
                                              return next
                                            })
                                          }}
                                          className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-950/60 px-2 py-1 text-[11px] text-slate-200"
                                          placeholder="该句文本"
                                        />
                                        <div className="flex shrink-0 items-center gap-1 sm:flex-col sm:items-stretch">
                                          <button
                                            type="button"
                                            title="在播放器中从此句起点播放"
                                            onClick={() => seekToSegment(c, seg)}
                                            className="inline-flex items-center justify-center gap-0.5 rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-emerald-600/60 hover:text-emerald-300"
                                          >
                                            <Play className="w-3 h-3" />
                                            播放
                                          </button>
                                          <button
                                            type="button"
                                            title="删除该句"
                                            onClick={() =>
                                              patchAsrSegments(c.id, c, (segs) => segs.filter((_, j) => j !== si))
                                            }
                                            className="inline-flex items-center justify-center rounded border border-slate-700 px-1.5 py-0.5 text-slate-500 hover:border-red-500/50 hover:text-red-400"
                                          >
                                            <Trash2 className="w-3.5 h-3.5" />
                                          </button>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>

                              <div>
                                <div className="text-[11px] text-slate-500 mb-1">VLM</div>
                                <textarea
                                  value={st?.vlm_description ?? safeStr(c.vlm_description)}
                                  onChange={(e) => setEditField(c.id, 'vlm_description', e.target.value)}
                                  rows={4}
                                  className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-800 text-xs text-slate-200 outline-none focus:border-indigo-500 transition-colors"
                                />
                              </div>
                            </div>

                            {st?.dirty && (
                              <div className="text-[11px] text-amber-400/80 flex items-center gap-1">
                                <Check className="w-3.5 h-3.5" />
                                有未保存修改
                              </div>
                            )}
                            {st?.error && <div className="text-[11px] text-red-400">{st.error}</div>}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

