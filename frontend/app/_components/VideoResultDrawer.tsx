'use client'

import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { X, Loader2, Save, Search, Check, Film, Subtitles, ListTree, Play, Trash2, Plus, RotateCcw, Wand2, Info, Settings2 } from 'lucide-react'
import { API_BASE_URL, apiClient, clipsApi, asrApi, processJobsApi, type AsrSegmentJson, type AsrCorrectResult, type AsrCorrectBatchResult, type ClipResult } from '@/lib/api'
import { videoStreamUrl, clipStreamUrl, fmt } from '@/app/match/_components/types'
import { useToast } from '@/components/ui/toast-provider'
import { BatchCorrectReviewModal } from '@/app/_components/BatchCorrectReviewModal'
import { BatchCorrectConfirmDialog } from '@/app/_components/BatchCorrectConfirmDialog'

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
  abstract_summary: string
  keywords: string[]
  emotion_tags: string[]
  /** 关键词/情绪是否有改动；未改动则保存不带上（避免误清） */
  tagsDirty: boolean
  dirty: boolean
  saving: boolean
  error: string
}

function parseStrList(raw: string | null | undefined): string[] {
  if (!raw || !String(raw).trim()) return []
  try {
    const data = JSON.parse(String(raw)) as unknown
    if (!Array.isArray(data)) return []
    return data
      .map((x) => String(x ?? '').trim())
      .filter((s) => !!s)
  } catch {
    return []
  }
}

function tagsToInput(arr: string[]): string {
  return arr.join('、')
}

function inputToTags(s: string): string[] {
  return s
    .split(/[、,，\n]/)
    .map((t) => t.trim())
    .filter((t) => !!t)
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
  const [videoQ, setVideoQ] = useState('')
  const [q, setQ] = useState('')
  const [activeClipId, setActiveClipId] = useState<string>('')
  const [playerMode, setPlayerMode] = useState<'video' | 'clip'>('video')
  const [resultsTab, setResultsTab] = useState<'preview' | 'details'>('details')
  const [asrPreviewMode, setAsrPreviewMode] = useState<'timeline' | 'plain'>('timeline')

  const [editing, setEditing] = useState<Record<string, EditState>>({})
  const [reprocessBusyId, setReprocessBusyId] = useState<string | null>(null)
  // LLM 校准：correcting[clipId]=true 表示该校准进行中；correctPreview[clipId] 存预览结果
  const [correcting, setCorrecting] = useState<Record<string, boolean>>({})
  const [correctPreview, setCorrectPreview] = useState<Record<string, AsrCorrectResult>>({})
  const [applyingCorrect, setApplyingCorrect] = useState<string | null>(null)
  // 倾向性校准提示词：globalHint 为全局默认（懒加载），correctHint[clipId] 为该片段临时输入
  const [globalHint, setGlobalHint] = useState<string | null>(null)
  const [correctHint, setCorrectHint] = useState<Record<string, string>>({})
  // 单 clip 提示词框是否展开（默认折叠，省空间）
  const [hintOpen, setHintOpen] = useState<Record<string, boolean>>({})
  // 批量校准全部：running 时显示进度；result 存上次结果摘要
  const [batchCorrect, setBatchCorrect] = useState<{ running: boolean; done: number; total: number; changed: number } | null>(null)
  // 批量审核弹窗：previewData 存预览结果，submitting 为提交写库中
  const [reviewOpen, setReviewOpen] = useState(false)
  const [reviewData, setReviewData] = useState<AsrCorrectBatchResult | null>(null)
  const [reviewSubmitting, setReviewSubmitting] = useState(false)
  // 批量校准确认弹窗（带提示词输入）：点「批量校准全部」先弹此
  const [batchConfirmOpen, setBatchConfirmOpen] = useState(false)

  const videoRef = useRef<HTMLVideoElement | null>(null)

  useEffect(() => {
    if (!open) return
    setCurVideoId(initialVideoId)
    setVideoQ('')
  }, [open, initialVideoId])

  const filteredVideoOptions = useMemo(() => {
    const kw = videoQ.trim().toLowerCase()
    const all = videoOptions || []
    if (!kw) return all
    return all.filter((v) => {
      const name = safeStr(v.name).toLowerCase()
      return name.includes(kw) || v.id.toLowerCase().includes(kw)
    })
  }, [videoOptions, videoQ])

  const reloadClips = useCallback(async (videoId: string) => {
    const rows = await clipsApi.listByVideo(videoId)
    setClips(rows || [])
    const map: Record<string, EditState> = {}
    ;(rows || []).forEach((c) => {
      map[c.id] = {
        asr_text: safeStr(c.asr_text),
        asr_segments: parseAsrSegments(c.asr_segments),
        asrSegmentsDirty: false,
        vlm_description: safeStr(c.vlm_description),
        abstract_summary: safeStr(c.abstract_summary),
        keywords: parseStrList(c.keywords),
        emotion_tags: parseStrList(c.emotion_tags),
        tagsDirty: false,
        dirty: false,
        saving: false,
        error: '',
      }
    })
    setEditing(map)
    return rows || []
  }, [])

  useEffect(() => {
    if (!open) return
    if (!curVideoId) return
    setLoading(true)
    setErr('')
    reloadClips(curVideoId)
      .then((rows) => {
        setActiveClipId(rows?.[0]?.id || '')
      })
      .catch((e: unknown) => {
        setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '加载失败')
      })
      .finally(() => setLoading(false))
  }, [open, curVideoId, reloadClips])

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase()
    if (!kw) return clips
    return clips.filter((c) => {
      const a = safeStr(c.asr_text).toLowerCase()
      const v = safeStr(c.vlm_description).toLowerCase()
      const summary = safeStr(c.abstract_summary).toLowerCase()
      const tagsBlob = [...parseStrList(c.keywords), ...parseStrList(c.emotion_tags)].join(' ').toLowerCase()
      const stLocal = editing[c.id]
      const segs = stLocal?.asr_segments ?? parseAsrSegments(c.asr_segments)
      const segBlob = joinSegmentsText(segs).toLowerCase()
      return (
        a.includes(kw) ||
        v.includes(kw) ||
        summary.includes(kw) ||
        tagsBlob.includes(kw) ||
        segBlob.includes(kw) ||
        c.id.toLowerCase().includes(kw)
      )
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

  const setEditField = (clipId: string, field: 'asr_text' | 'vlm_description' | 'abstract_summary', value: string) => {
    setEditing((prev) => {
      const cur = prev[clipId] || {
        asr_text: '',
        asr_segments: [],
        asrSegmentsDirty: false,
        vlm_description: '',
        abstract_summary: '',
        keywords: [],
        emotion_tags: [],
        tagsDirty: false,
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
        abstract_summary: safeStr(clip.abstract_summary),
        keywords: parseStrList(clip.keywords),
        emotion_tags: parseStrList(clip.emotion_tags),
        tagsDirty: false,
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

  /** 编辑智能标注的关键词 / 情绪（输入框以「、」分隔） */
  const setTagsField = (clipId: string, field: 'keywords' | 'emotion_tags', value: string) => {
    setEditing((prev) => {
      const cur = prev[clipId]
      if (!cur) return prev
      return {
        ...prev,
        [clipId]: {
          ...cur,
          [field]: inputToTags(value),
          tagsDirty: true,
          dirty: true,
          error: '',
        },
      }
    })
  }

  /** 懒加载全局校准提示词（用于输入框 placeholder/预填） */
  const ensureGlobalHint = async () => {
    if (globalHint !== null) return globalHint
    try {
      const cfg = await apiClient.get<unknown, Record<string, { value?: string }>>('/api/config')
      const gh = (cfg?.['asr_correct_hint']?.value ?? '').trim()
      setGlobalHint(gh)
      return gh
    } catch {
      setGlobalHint('')
      return ''
    }
  }

  /** 取某片段校准提示词：有临时输入则用之，否则交给后端用全局（传 undefined） */
  const resolveHintFor = (clipId: string): string | undefined => {
    const local = correctHint[clipId]
    if (local === undefined) return undefined
    return local
  }

  /** 触发单片段 LLM 校准（仅预览） */
  const runCorrectPreview = async (clipId: string) => {
    if (correcting[clipId]) return
    const clip = clips.find((c) => c.id === clipId)
    if (!clip) return
    if (!safeStr(clip.asr_text).trim() && !parseAsrSegments(clip.asr_segments).length) {
      toast.error('该片段暂无 ASR 文本，无法校准')
      return
    }
    await ensureGlobalHint()
    setCorrecting((p) => ({ ...p, [clipId]: true }))
    // 清掉旧预览
    setCorrectPreview((p) => {
      if (!p[clipId]) return p
      const next = { ...p }
      delete next[clipId]
      return next
    })
    try {
      const res = await asrApi.correctClip(clipId, false, resolveHintFor(clipId))
      setCorrectPreview((p) => ({ ...p, [clipId]: res }))
      if (!res.changed) {
        toast.success('LLM 校准完成：未发现明显错误')
      }
    } catch (e: unknown) {
      toast.error(apiDetailMessage(e))
    } finally {
      setCorrecting((p) => ({ ...p, [clipId]: false }))
    }
  }

  /** 应用校准结果（写库 + 更新本地 state + 提示重算向量） */
  const applyCorrect = async (clipId: string) => {
    if (applyingCorrect) return
    setApplyingCorrect(clipId)
    try {
      const res = await asrApi.correctClip(clipId, true, resolveHintFor(clipId))
      // 同步本地 clips 与 editing state
      const newSegJson = res.corrected_segments.length
        ? JSON.stringify(res.corrected_segments)
        : null
      setClips((prev) =>
        prev.map((c) =>
          c.id === clipId
            ? { ...c, asr_text: res.corrected_text, asr_segments: newSegJson }
            : c,
        ),
      )
      setEditing((prev) => {
        if (!prev[clipId]) return prev
        return {
          ...prev,
          [clipId]: {
            ...prev[clipId],
            asr_text: res.corrected_text,
            asr_segments: res.corrected_segments,
            asrSegmentsDirty: false,
            dirty: false,
            error: '',
          },
        }
      })
      // 清掉预览
      setCorrectPreview((p) => {
        const next = { ...p }
        delete next[clipId]
        return next
      })
      if (res.vector_stale) {
        toast.success('校准已应用。ASR 文本已变更，建议重跑向量以保持检索一致')
      } else {
        toast.success('校准已应用')
      }
    } catch (e: unknown) {
      toast.error(apiDetailMessage(e))
    } finally {
      setApplyingCorrect(null)
    }
  }

  const dismissCorrect = (clipId: string) => {
    setCorrectPreview((p) => {
      const next = { ...p }
      delete next[clipId]
      return next
    })
  }

  /** 点「批量校准全部」：打开带提示词输入的确认弹窗 */
  const openBatchCorrect = async () => {
    if (!curVideoId || batchCorrect?.running) return
    if (clips.length === 0) {
      toast.error('当前没有可校准的片段')
      return
    }
    await ensureGlobalHint()
    setBatchConfirmOpen(true)
  }

  /** 批量校准当前视频全部片段 ASR：预览 → 审核弹层 → 写库 */
  const runBatchCorrect = async (hint: string) => {
    if (!curVideoId || batchCorrect?.running) return
    setBatchCorrect({ running: true, done: 0, total: clips.length, changed: 0 })
    try {
      // 先 apply=false 预览，拿到句级 diff 供审核；携带用户输入的提示词
      const res = await asrApi.correctBatch(curVideoId, {
        apply: false,
        ...(hint.trim() ? { hint: hint.trim() } : {}),
      })
      const failed = res.total - res.success
      // 全部失败：不弹空审核层，直接报错
      if (res.success === 0) {
        toast.error(
          `批量校准全部失败（${failed}/${res.total}）。请检查「设置」里的 LLM API Key 是否有效/有余额。`,
        )
        setBatchCorrect(null)
        setBatchConfirmOpen(false)
        return
      }
      // 全部成功但无改动
      if (res.changed === 0) {
        toast.success(`批量校准完成：${res.success}/${res.total} 成功，未发现明显错误，无需审核`)
        setBatchCorrect({ running: false, done: res.success, total: res.total, changed: 0 })
        setBatchConfirmOpen(false)
        return
      }
      // 有改动（可能伴随部分失败）→ 关闭确认弹窗，弹审核层
      setBatchConfirmOpen(false)
      setReviewData(res)
      setReviewOpen(true)
      setBatchCorrect({ running: false, done: res.success, total: res.total, changed: res.changed })
    } catch (e: unknown) {
      toast.error(apiDetailMessage(e))
      setBatchCorrect(null)
      setBatchConfirmOpen(false)
    }
  }

  /** 审核弹层提交：按用户审核结果写库 */
  const submitReview = async (finalized: Record<string, AsrSegmentJson[]>) => {
    if (!curVideoId) return
    setReviewSubmitting(true)
    try {
      // 逐 clip 写库（复用 clipsApi.update，与单片段保存一致）
      let written = 0
      let changedClips = 0
      for (const [clipId, segs] of Object.entries(finalized)) {
        const newText = segs.map((s) => s.text ?? '').join('')
        // 判断该 clip 是否相对原库有改动
        const oldClip = clips.find((c) => c.id === clipId)
        const oldText = safeStr(oldClip?.asr_text)
        if (newText !== oldText) changedClips += 1
        await clipsApi.update(clipId, {
          asr_text: newText,
          asr_segments: JSON.stringify(segs),
        })
        written += 1
      }
      // 刷新本地数据
      await reloadClips(curVideoId)
      setCorrectPreview({})
      setReviewOpen(false)
      setReviewData(null)
      const hint = changedClips > 0 ? '。ASR 已变更，建议重跑向量' : ''
      toast.success(`审核结果已写库：${written} 个片段${hint}`)
    } catch (e: unknown) {
      toast.error(apiDetailMessage(e))
    } finally {
      setReviewSubmitting(false)
    }
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
        abstract_summary: string
        asr_segments?: string | null
        keywords?: string | null
        emotion_tags?: string | null
      } = {
        asr_text: st.asr_text,
        vlm_description: st.vlm_description,
        abstract_summary: st.abstract_summary,
      }
      if (st.asrSegmentsDirty) {
        payload.asr_segments = JSON.stringify(st.asr_segments)
      }
      if (st.tagsDirty) {
        payload.keywords = JSON.stringify(st.keywords)
        payload.emotion_tags = JSON.stringify(st.emotion_tags)
      }
      await clipsApi.update(clipId, payload)
      setClips((prev) =>
        prev.map((c) =>
          c.id === clipId
            ? {
                ...c,
                asr_text: st.asr_text,
                vlm_description: st.vlm_description,
                abstract_summary: st.abstract_summary,
                ...(st.asrSegmentsDirty ? { asr_segments: payload.asr_segments ?? null } : {}),
                ...(st.tagsDirty
                  ? {
                      keywords: payload.keywords ?? null,
                      emotion_tags: payload.emotion_tags ?? null,
                    }
                  : {}),
              }
            : c
        )
      )
      setEditing((p) => ({
        ...p,
        [clipId]: {
          ...p[clipId],
          saving: false,
          dirty: false,
          asrSegmentsDirty: false,
          tagsDirty: false,
          error: '',
        },
      }))
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '保存失败'
      setEditing((p) => ({ ...p, [clipId]: { ...p[clipId], saving: false, error: msg } }))
    }
  }

  const enqueueClipReprocess = async (
    clipId: string,
    preset: 'asr_only' | 'vlm_only' | 'asr_vlm' | 'embed_only' | 'enrich_only',
    navigateToProcess: boolean,
  ) => {
    if (!curVideoId || reprocessBusyId) return
    const skip_steps =
      preset === 'asr_only'
        ? (['split', 'extract_frames', 'vlm', 'enrich'] as const)
        : preset === 'vlm_only'
          ? (['split', 'asr'] as const)
          : preset === 'embed_only'
            ? (['split', 'extract_frames', 'asr', 'vlm', 'enrich'] as const)
            : preset === 'enrich_only'
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
              <div className="w-[520px] max-w-[58vw] flex items-center gap-2">
                <div className="relative flex-[1.15] min-w-[170px]">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
                  <input
                    value={videoQ}
                    onChange={(e) => setVideoQ(e.target.value)}
                    placeholder="搜索切换视频（名称 / ID）..."
                    className="w-full pl-8 pr-2 py-1.5 rounded-md bg-slate-900/60 border border-slate-700 text-xs text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500"
                  />
                </div>
                <select
                  value={curVideoId}
                  onChange={(e) => setCurVideoId(e.target.value)}
                  className="flex-1 min-w-[170px] px-2 py-1.5 rounded-md bg-slate-900/60 border border-slate-700 text-xs text-slate-200 outline-none focus:border-indigo-500"
                >
                  {filteredVideoOptions.length === 0 ? (
                    <option value="" disabled>
                      无匹配视频
                    </option>
                  ) : (
                    filteredVideoOptions.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))
                  )}
                </select>
                <span className="shrink-0 text-[11px] text-slate-500">
                  {filteredVideoOptions.length}/{videoOptions.length}
                </span>
              </div>
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
                  placeholder="搜索 ASR / VLM / 标注 ..."
                  className="w-full pl-9 pr-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500 transition-colors"
                />
              </div>
              <button
                type="button"
                title="用 LLM 一次性校准当前视频全部片段的 ASR（直接覆盖，使用全局提示词）"
                disabled={!curVideoId || clips.length === 0 || !!batchCorrect?.running}
                onClick={() => void openBatchCorrect()}
                className="inline-flex items-center gap-1 rounded-lg border border-indigo-700/50 bg-indigo-900/30 px-2.5 py-2 text-xs text-indigo-200 hover:border-indigo-500 hover:bg-indigo-800/40 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
              >
                {batchCorrect?.running ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Wand2 className="w-3.5 h-3.5" />
                )}
                {batchCorrect?.running ? '校准中…' : '批量校准全部'}
              </button>
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

            <div className="flex-1 min-h-0 overflow-auto styled-scrollbar">
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
                    <div className="flex-1 min-h-0 overflow-auto styled-scrollbar rounded-lg border border-slate-800 bg-slate-900/30 divide-y divide-slate-800">
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
                                  重跑 ASR+向量
                                </button>
                                <button
                                  type="button"
                                  title="对本片段重跑 VLM + 向量（不切分，保证检索一致）"
                                  disabled={!!reprocessBusyId || !curVideoId}
                                  onClick={() => void enqueueClipReprocess(c.id, 'vlm_only', false)}
                                  className="text-xs px-2 py-1 rounded-md border border-slate-700 bg-slate-900/40 text-slate-300 hover:border-cyan-600/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-0.5"
                                >
                                  {reprocessBusyId === c.id ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <RotateCcw className="w-3.5 h-3.5" />
                                  )}
                                  重跑 VLM+向量
                                </button>
                                <button
                                  type="button"
                                  title="本片段 ASR + VLM + 向量 重跑（不切分）"
                                  disabled={!!reprocessBusyId || !curVideoId}
                                  onClick={() => void enqueueClipReprocess(c.id, 'asr_vlm', false)}
                                  className="text-xs px-2 py-1 rounded-md border border-slate-700 bg-slate-900/40 text-slate-300 hover:border-indigo-600/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-0.5"
                                >
                                  {reprocessBusyId === c.id ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <RotateCcw className="w-3.5 h-3.5" />
                                  )}
                                  ASR+VLM+向量
                                </button>
                                <button
                                  type="button"
                                  title="仅对本片段重跑向量（不切分）"
                                  disabled={!!reprocessBusyId || !curVideoId}
                                  onClick={() => void enqueueClipReprocess(c.id, 'embed_only', false)}
                                  className="text-xs px-2 py-1 rounded-md border border-slate-700 bg-slate-900/40 text-slate-300 hover:border-emerald-600/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-0.5"
                                >
                                  {reprocessBusyId === c.id ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <RotateCcw className="w-3.5 h-3.5" />
                                  )}
                                  重跑向量
                                </button>
                                <button
                                  type="button"
                                  title="对本片段重新生成智能标注（旁白适配摘要/关键词/情绪，需配置 LLM Key）。标注后重算该片段向量"
                                  disabled={!!reprocessBusyId || !curVideoId}
                                  onClick={() => void enqueueClipReprocess(c.id, 'enrich_only', false)}
                                  className="text-xs px-2 py-1 rounded-md border border-slate-700 bg-slate-900/40 text-slate-300 hover:border-indigo-500/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-0.5"
                                >
                                  {reprocessBusyId === c.id ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <RotateCcw className="w-3.5 h-3.5" />
                                  )}
                                  重跑智能标注+向量
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
                                <div className="flex items-center justify-between mb-1">
                                  <div className="text-[11px] text-slate-500">ASR（全文）</div>
                                  <div className="flex items-center gap-1">
                                    <button
                                      type="button"
                                      title="展开/收起校准提示词（覆盖全局设置）"
                                      onClick={() => setHintOpen((p) => ({ ...p, [c.id]: !p[c.id] }))}
                                      className={`relative inline-flex items-center gap-0.5 rounded-md border px-1.5 py-0.5 text-[11px] transition-colors ${
                                        correctHint[c.id]?.trim()
                                          ? 'border-indigo-500/70 bg-indigo-900/40 text-indigo-200'
                                          : hintOpen[c.id]
                                            ? 'border-slate-600 bg-slate-800/60 text-slate-300'
                                            : 'border-slate-700 bg-slate-900/40 text-slate-500 hover:text-slate-300'
                                      }`}
                                    >
                                      <Settings2 className="w-3 h-3" />
                                      {correctHint[c.id]?.trim() && (
                                        <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-indigo-400" />
                                      )}
                                    </button>
                                    <button
                                      type="button"
                                      title="用 LLM 校准 ASR 识别错误（同音/形近错字、标点），保留原句级时间轴"
                                      disabled={!!correcting[c.id]}
                                      onClick={() => void runCorrectPreview(c.id)}
                                      className="inline-flex items-center gap-1 rounded-md border border-indigo-700/50 bg-indigo-900/30 px-2 py-0.5 text-[11px] text-indigo-200 hover:border-indigo-500 hover:bg-indigo-800/40 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                    >
                                      {correcting[c.id] ? (
                                        <Loader2 className="w-3 h-3 animate-spin" />
                                      ) : (
                                        <Wand2 className="w-3 h-3" />
                                      )}
                                      LLM 校准
                                    </button>
                                  </div>
                                </div>
                                <textarea
                                  value={st?.asr_text ?? safeStr(c.asr_text)}
                                  onChange={(e) => setEditField(c.id, 'asr_text', e.target.value)}
                                  rows={3}
                                  className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-800 text-xs text-slate-200 outline-none focus:border-indigo-500 transition-colors"
                                  placeholder="整段转写；修改下方句级时会按句拼接覆盖此处"
                                />
                              </div>

                              {/* 倾向性校准提示词（默认折叠，省空间；齿轮切换展开） */}
                              {hintOpen[c.id] && (
                                <div className="space-y-1">
                                  <div className="text-[11px] text-slate-500 flex items-center gap-1">
                                    校准提示词（可选）
                                    <span title="填入领域词汇/专有名词/口音特点，提升领域词修正率。留空则用「设置-语音识别」里的全局值" className="text-slate-600 cursor-help">
                                      <Info className="w-3 h-3 inline" />
                                    </span>
                                  </div>
                                  <textarea
                                    value={correctHint[c.id] ?? ''}
                                    onChange={(e) =>
                                      setCorrectHint((p) => ({ ...p, [c.id]: e.target.value }))
                                    }
                                    rows={2}
                                    className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900/50 border border-slate-800 text-[11px] text-slate-200 outline-none focus:border-indigo-500 transition-colors resize-y"
                                    placeholder={
                                      globalHint
                                        ? `留空用全局：${globalHint}`
                                        : '留空用全局设置。例：这是面巾纸视频，「面积纸」应为「面巾纸」'
                                    }
                                  />
                                </div>
                              )}

                              {/* LLM 校准 diff 预览 */}
                              {correctPreview[c.id] && (() => {
                                const cp = correctPreview[c.id]
                                const hasSegs = cp.original_segments.length > 0
                                return (
                                  <div className="rounded-lg border border-indigo-800/60 bg-indigo-950/20 p-2.5 space-y-2">
                                    <div className="flex items-center justify-between">
                                      <div className="flex items-center gap-1.5 text-[11px] text-indigo-300">
                                        <Wand2 className="w-3.5 h-3.5 shrink-0" />
                                        <span>LLM 校准预览</span>
                                        {cp.changed ? (
                                          <span className="text-amber-400">· 有改动，请确认</span>
                                        ) : (
                                          <span className="text-slate-500">· 未发现明显错误</span>
                                        )}
                                      </div>
                                      <div className="flex items-center gap-1.5">
                                        <button
                                          type="button"
                                          disabled={!cp.changed || applyingCorrect === c.id}
                                          onClick={() => void applyCorrect(c.id)}
                                          className="inline-flex items-center gap-1 rounded-md border border-emerald-700/50 bg-emerald-900/30 px-2 py-0.5 text-[11px] text-emerald-200 hover:border-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                        >
                                          {applyingCorrect === c.id ? (
                                            <Loader2 className="w-3 h-3 animate-spin" />
                                          ) : (
                                            <Check className="w-3 h-3" />
                                          )}
                                          应用校准
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => dismissCorrect(c.id)}
                                          className="rounded-md border border-slate-700 px-2 py-0.5 text-[11px] text-slate-400 hover:text-slate-200 transition-colors"
                                        >
                                          放弃
                                        </button>
                                      </div>
                                    </div>

                                    {hasSegs ? (
                                      <div className="max-h-[200px] space-y-1 overflow-y-auto styled-scrollbar pr-0.5">
                                        {cp.corrected_segments.map((seg, si) => {
                                          const orig = cp.original_segments[si]?.text ?? ''
                                          const changed = seg.text !== orig
                                          return (
                                            <div
                                              key={si}
                                              className={`rounded-md border p-1.5 text-[11px] ${
                                                changed
                                                  ? 'border-amber-700/40 bg-amber-950/15'
                                                  : 'border-slate-800/60 bg-slate-900/30'
                                              }`}
                                            >
                                              <div className="text-slate-500 mb-0.5">
                                                #{si + 1} · {seg.start.toFixed(2)}s—{seg.end.toFixed(2)}s
                                              </div>
                                              <div className="text-slate-500 line-through decoration-slate-600 break-all">
                                                {orig || '（空）'}
                                              </div>
                                              {changed && (
                                                <div className="text-emerald-300 break-all mt-0.5">
                                                  {seg.text}
                                                </div>
                                              )}
                                            </div>
                                          )
                                        })}
                                      </div>
                                    ) : (
                                      <div className="space-y-1">
                                        <div className="text-[11px] text-slate-500 break-all line-through decoration-slate-600">
                                          {cp.original_text || '（空）'}
                                        </div>
                                        <div className="text-[11px] text-emerald-300 break-all">
                                          {cp.corrected_text}
                                        </div>
                                      </div>
                                    )}
                                    {cp.changed && (
                                      <p className="text-[10px] leading-snug text-slate-500">
                                        应用后将覆盖 ASR 全文与句级文字（时间轴保留不变），并提示重跑向量。
                                      </p>
                                    )}
                                  </div>
                                )
                              })()}

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
                                  <div className="max-h-[220px] space-y-1.5 overflow-y-auto styled-scrollbar pr-0.5">
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

                              <div className="rounded-lg border border-indigo-900/40 bg-indigo-950/10 p-2.5 space-y-2">
                                <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
                                  <ListTree className="w-3.5 h-3.5 text-indigo-400/90 shrink-0" />
                                  <span>智能标注（enrich）</span>
                                  <span className="text-slate-600">用于抹平旁白-画面语义鸿沟，提升旁白检索命中率；可手动修正</span>
                                </div>
                                <div>
                                  <div className="text-[11px] text-slate-500 mb-1">旁白适配摘要（抽象层表述，如「离别与抉择」）</div>
                                  <textarea
                                    value={st?.abstract_summary ?? safeStr(c.abstract_summary)}
                                    onChange={(e) => setEditField(c.id, 'abstract_summary', e.target.value)}
                                    rows={2}
                                    placeholder="无标注时留空；处理时若开启智能标注会自动生成"
                                    className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-800 text-xs text-slate-200 outline-none focus:border-indigo-500 transition-colors"
                                  />
                                </div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                  <div>
                                    <div className="text-[11px] text-slate-500 mb-1">关键词（用「、」或逗号分隔）</div>
                                    <input
                                      type="text"
                                      value={tagsToInput(st?.keywords ?? [])}
                                      onChange={(e) => setTagsField(c.id, 'keywords', e.target.value)}
                                      placeholder="如：离别、现实、争吵"
                                      className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-800 text-xs text-slate-200 outline-none focus:border-indigo-500 transition-colors"
                                    />
                                  </div>
                                  <div>
                                    <div className="text-[11px] text-slate-500 mb-1">情绪标签（用「、」或逗号分隔）</div>
                                    <input
                                      type="text"
                                      value={tagsToInput(st?.emotion_tags ?? [])}
                                      onChange={(e) => setTagsField(c.id, 'emotion_tags', e.target.value)}
                                      placeholder="如：悲伤、压抑"
                                      className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-800 text-xs text-slate-200 outline-none focus:border-indigo-500 transition-colors"
                                    />
                                  </div>
                                </div>
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

      {/* 批量校准确认弹窗（带辅助提示词输入） */}
      <BatchCorrectConfirmDialog
        open={batchConfirmOpen}
        totalClips={clips.length}
        globalHint={globalHint}
        running={!!batchCorrect?.running}
        onConfirm={(hint) => void runBatchCorrect(hint)}
        onCancel={() => {
          if (!batchCorrect?.running) setBatchConfirmOpen(false)
        }}
      />

      {/* 批量校准审核弹层（fixed 定位，脱离抽屉） */}
      <BatchCorrectReviewModal
        open={reviewOpen}
        data={reviewData}
        submitting={reviewSubmitting}
        onClose={() => {
          if (!reviewSubmitting) {
            setReviewOpen(false)
            setReviewData(null)
          }
        }}
        onSubmit={submitReview}
      />
    </div>
  )
}

