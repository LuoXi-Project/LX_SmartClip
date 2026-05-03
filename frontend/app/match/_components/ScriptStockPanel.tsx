'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import Link from 'next/link'
import {
  ChevronDown,
  ChevronUp,
  ChevronsDown,
  ChevronsUp,
  Clapperboard,
  Copy,
  Download,
  ExternalLink,
  Film,
  GripVertical,
  Layers,
  Loader2,
  Mic,
  Plus,
  Scissors,
  Search,
  Sparkles,
  SplitSquareHorizontal,
  Trash2,
} from 'lucide-react'
import type { Video } from '@/lib/api'
import {
  API_BASE_URL,
  formatFastApiDetail,
  scriptStockApi,
  type ScriptStockAudioMode,
  type ScriptStockMaterialTtsFill,
  type ScriptStockMaterialTtsLonger,
  type ScriptStockPexelsCacheItemApi,
  type ScriptStockPexelsVideoApi,
  type ScriptStockTimelineMode,
  type ScriptStockComposeSegmentApi,
  type ScriptStockVideoExtendPolicy,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'
import { DEFAULT_SUBTITLE_STYLE, type ClipTrimRange, type SubtitleStyle } from './types'
import {
  appendIdToOrderedList,
  orderPositionsForKey,
  toggleIdInOrderedList,
} from '@/lib/match/orderedSelection'
import { OrderedPickCard } from './OrderedPickCard'
import { SegmentLocalLibraryBlock } from './SegmentLocalLibraryBlock'
import { StockLibraryTrimDialog } from './StockLibraryTrimDialog'
import {
  computeNextLibraryTrimSlots,
  defaultLibraryTrimForVideo,
  libraryTrimSlotIsCustom,
} from './clipTrim'

type SourceTab = 'local' | 'pexels'

type StockSegState = {
  id: string
  text: string
  sourceTab: SourceTab
  searchQuery: string
  /** 本地素材库多选，顺序即成片拼接顺序（仅「仅 TTS」允许多条） */
  localVideoIds: string[]
  /** 与 localVideoIds 同序的选用区间（秒） */
  libraryTrimSlots?: ClipTrimRange[]
  pexelsResults: ScriptStockPexelsVideoApi[]
  searching: boolean
  downloadingId: number | null
  /** 已下载的 Pexels 文件（storage 相对路径），勾选顺序即成片顺序 */
  pexelsStoredRelPaths: string[]
}

function newSeg(text: string): StockSegState {
  return {
    id: `ss_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
    text,
    sourceTab: 'pexels',
    searchQuery: '',
    localVideoIds: [],
    libraryTrimSlots: undefined,
    pexelsResults: [],
    searching: false,
    downloadingId: null,
    pexelsStoredRelPaths: [],
  }
}

function fmtBytes(n: number) {
  const x = Number(n) || 0
  if (x < 1024) return `${x} B`
  if (x < 1048576) return `${(x / 1024).toFixed(1)} KB`
  return `${(x / 1048576).toFixed(1)} MB`
}

function bestCachedRelForPexelsId(items: ScriptStockPexelsCacheItemApi[], videoId: number): string | undefined {
  const hits = items.filter((it) => it.pexels_video_id === videoId)
  if (!hits.length) return undefined
  hits.sort((a, b) => b.mtime - a.mtime)
  return hits[0].stored_rel_path
}

const STOCK_SEG_DRAG_MIME = 'application/x-smartclip-stock-seg-id'

export function ScriptStockPanel({
  subtitleEnabled = false,
  subtitleStyle,
}: {
  /** 与智能剪辑侧栏「字幕成片」一致；开启时合成会硬烧字幕 */
  subtitleEnabled?: boolean
  subtitleStyle?: SubtitleStyle
}) {
  const toast = useToast()
  const [fullScript, setFullScript] = useState('')
  const [topic, setTopic] = useState('')
  const [styleHint, setStyleHint] = useState('')
  const [numParas, setNumParas] = useState(5)
  const [generatingScript, setGeneratingScript] = useState(false)
  const [splitting, setSplitting] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [segments, setSegments] = useState<StockSegState[]>([])
  const [projectName, setProjectName] = useState('文案素材成片')
  const [composing, setComposing] = useState(false)
  /** 最近一次合成成功的完整访问 URL（弹窗被拦时仍可复制） */
  const [lastComposeUrl, setLastComposeUrl] = useState<string | null>(null)
  const [lastComposeFilename, setLastComposeFilename] = useState<string | null>(null)
  const [audioMode, setAudioMode] = useState<ScriptStockAudioMode>('tts_only')
  const [ttsVolumeDb, setTtsVolumeDb] = useState(0)
  const [originalVolumeDb, setOriginalVolumeDb] = useState(-6)
  const [timelineMode, setTimelineMode] = useState<ScriptStockTimelineMode>('follow_narration')
  const [videoExtendPolicy, setVideoExtendPolicy] = useState<ScriptStockVideoExtendPolicy>('loop_video_to_cover')
  const [materialTtsFill, setMaterialTtsFill] = useState<ScriptStockMaterialTtsFill>('pad_silence')
  const [materialTtsLonger, setMaterialTtsLonger] = useState<ScriptStockMaterialTtsLonger>('stretch_audio')
  const [pexelsCacheItems, setPexelsCacheItems] = useState<ScriptStockPexelsCacheItemApi[]>([])
  const [pexelsCacheLoading, setPexelsCacheLoading] = useState(false)

  /** 本地素材库「自选区间」弹窗对应的段落 id */
  const [trimDialogSegId, setTrimDialogSegId] = useState<string | null>(null)

  /** 各段拉取的素材元数据合并（自选区间 / 合成） */
  const [libraryVideoMap, setLibraryVideoMap] = useState<Record<string, Video>>({})
  const mergeLibraryListItems = useCallback((items: Video[]) => {
    setLibraryVideoMap((prev) => {
      const next = { ...prev }
      for (const v of items) next[v.id] = v
      return next
    })
  }, [])

  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dropTargetId, setDropTargetId] = useState<string | null>(null)
  const [flashId, setFlashId] = useState<string | null>(null)
  const flashClearRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const libraryVideos = useMemo(() => Object.values(libraryVideoMap), [libraryVideoMap])

  const flashRow = useCallback((id: string) => {
    if (flashClearRef.current) clearTimeout(flashClearRef.current)
    setFlashId(id)
    flashClearRef.current = setTimeout(() => {
      setFlashId(null)
      flashClearRef.current = null
    }, 1100)
  }, [])

  useEffect(() => () => {
    if (flashClearRef.current) clearTimeout(flashClearRef.current)
  }, [])

  /** 拖动靠近视口上下边缘时自动滚动（与手动匹配一致） */
  useEffect(() => {
    if (!draggingId) return
    const margin = 88
    const maxStep = 22
    const onDragOver = (e: DragEvent) => {
      const y = e.clientY
      if (y < margin) {
        const k = 1 - y / margin
        window.scrollBy(0, -Math.ceil(maxStep * k))
      } else if (y > window.innerHeight - margin) {
        const k = 1 - (window.innerHeight - y) / margin
        window.scrollBy(0, Math.ceil(maxStep * k))
      }
    }
    document.addEventListener('dragover', onDragOver)
    return () => document.removeEventListener('dragover', onDragOver)
  }, [draggingId])

  const trimDialogSeg = useMemo(
    () => (trimDialogSegId ? segments.find((s) => s.id === trimDialogSegId) ?? null : null),
    [trimDialogSegId, segments],
  )
  const trimDialogInitialSlots = useMemo(() => {
    if (!trimDialogSeg?.localVideoIds.length) return [] as ClipTrimRange[]
    return trimDialogSeg.localVideoIds.map(
      (id, i) => trimDialogSeg.libraryTrimSlots?.[i] ?? defaultLibraryTrimForVideo(libraryVideos, id),
    )
  }, [trimDialogSeg, libraryVideos])

  const addSegment = () => {
    setSegments((prev) => [...prev, newSeg('')])
  }

  const removeSegment = (segId: string) => {
    setSegments((prev) => prev.filter((s) => s.id !== segId))
  }

  const clearAllSegments = () => {
    setSegments([])
  }

  const moveStockSegment = (fromId: string, toId: string) => {
    setSegments((prev) => {
      const list = [...prev]
      const from = list.findIndex((s) => s.id === fromId)
      const to = list.findIndex((s) => s.id === toId)
      if (from < 0 || to < 0 || from === to) return prev
      const [item] = list.splice(from, 1)
      list.splice(to, 0, item)
      return list
    })
  }

  const moveSegmentRel = (segId: string, action: 'up' | 'down' | 'top' | 'bottom') => {
    setSegments((prev) => {
      const list = [...prev]
      const from = list.findIndex((s) => s.id === segId)
      if (from < 0) return prev
      let to = from
      if (action === 'up') to = Math.max(0, from - 1)
      else if (action === 'down') to = Math.min(list.length - 1, from + 1)
      else if (action === 'top') to = 0
      else if (action === 'bottom') to = list.length - 1
      if (to === from) return prev
      const [item] = list.splice(from, 1)
      list.splice(to, 0, item)
      return list
    })
    flashRow(segId)
  }

  const loadPexelsCache = useCallback(async () => {
    setPexelsCacheLoading(true)
    try {
      const res = await scriptStockApi.pexelsListCache()
      setPexelsCacheItems(res.items || [])
    } catch {
      setPexelsCacheItems([])
    } finally {
      setPexelsCacheLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadPexelsCache()
  }, [loadPexelsCache])

  const handleDeletePexelsCache = async (storedRelPath: string) => {
    try {
      await scriptStockApi.pexelsDeleteFile({ stored_rel_path: storedRelPath })
      toast.success('已从本机删除该文件')
      setPexelsCacheItems((prev) => prev.filter((i) => i.stored_rel_path !== storedRelPath))
      setSegments((prev) =>
        prev.map((s) => ({
          ...s,
          pexelsStoredRelPaths: s.pexelsStoredRelPaths.filter((p) => p !== storedRelPath),
        })),
      )
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    }
  }

  const toggleLocalVideo = (segId: string, videoId: string, e: MouseEvent) => {
    setSegments((prev) =>
      prev.map((s) => {
        if (s.id !== segId) return s
        const cur = s.localVideoIds
        const next = e.shiftKey
          ? appendIdToOrderedList(cur, videoId)
          : toggleIdInOrderedList(cur, videoId)
        const nextSlots = computeNextLibraryTrimSlots(cur, s.libraryTrimSlots, next, libraryVideos)
        return { ...s, localVideoIds: next, libraryTrimSlots: nextSlots }
      }),
    )
  }

  const togglePexelsRel = (segId: string, rel: string, e: MouseEvent) => {
    if (!rel) return
    setSegments((prev) =>
      prev.map((s) => {
        if (s.id !== segId) return s
        const cur = s.pexelsStoredRelPaths
        const next = e.shiftKey
          ? appendIdToOrderedList(cur, rel)
          : toggleIdInOrderedList(cur, rel)
        return { ...s, pexelsStoredRelPaths: next }
      }),
    )
  }

  const handleSplit = async (mode: 'paragraph' | 'line') => {
    const script = fullScript.trim()
    if (!script) {
      toast.error('请先填写文案')
      return
    }
    setSplitting(true)
    try {
      const res = await scriptStockApi.split({ script, mode })
      const segs = (res.segments || []).map((t) => newSeg(t))
      if (!segs.length) {
        toast.error('未能分出有效段落')
        return
      }
      setSegments(segs)
      toast.success(`已分为 ${segs.length} 段，可在下方拖拽或箭头调整顺序、增删段落`)
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setSplitting(false)
    }
  }

  const handleGenerateScript = async () => {
    const t = topic.trim()
    if (!t) {
      toast.error('请填写主题或关键词')
      return
    }
    setGeneratingScript(true)
    try {
      const res = await scriptStockApi.generateScript({
        topic: t,
        style_hint: styleHint.trim(),
        num_paragraphs: numParas,
      })
      setFullScript(res.script || '')
      toast.success('文案已生成，可继续分段或编辑')
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setGeneratingScript(false)
    }
  }

  const handleSuggestAllQueries = async () => {
    if (!segments.length) {
      toast.error('请先分段')
      return
    }
    setSuggesting(true)
    try {
      const res = await scriptStockApi.suggestQueries({ segments: segments.map((s) => s.text) })
      const qs = res.queries || []
      setSegments((prev) =>
        prev.map((s, i) => ({
          ...s,
          searchQuery: (qs[i] || s.searchQuery || '').trim(),
        })),
      )
      toast.success('已为各段生成英文搜索词')
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setSuggesting(false)
    }
  }

  const searchPexelsForSeg = async (segId: string) => {
    const seg = segments.find((s) => s.id === segId)
    if (!seg) return
    const q = (seg.searchQuery || seg.text).trim()
    if (!q) {
      toast.error('请填写搜索词')
      return
    }
    setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, searching: true } : s)))
    try {
      const res = await scriptStockApi.pexelsSearch({ query: q, per_page: 12 })
      setSegments((prev) =>
        prev.map((s) => (s.id === segId ? { ...s, searching: false, pexelsResults: res.videos || [] } : s)),
      )
    } catch (e) {
      setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, searching: false } : s)))
      toast.error(formatFastApiDetail(e))
    }
  }

  const downloadPexels = async (segId: string, videoId: number) => {
    setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, downloadingId: videoId } : s)))
    try {
      const res = await scriptStockApi.pexelsDownload({ pexels_video_id: videoId, preferred_quality: 'hd' })
      const rel = res.stored_rel_path
      await loadPexelsCache()
      setSegments((prev) =>
        prev.map((s) =>
          s.id === segId
            ? {
                ...s,
                downloadingId: null,
                sourceTab: 'pexels',
                pexelsStoredRelPaths: appendIdToOrderedList(s.pexelsStoredRelPaths, rel),
              }
            : s,
        ),
      )
      toast.success('已下载并追加到本段顺序（Shift+点击可再叠同一条）')
    } catch (e) {
      setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, downloadingId: null } : s)))
      toast.error(formatFastApiDetail(e))
    }
  }

  const handleCompose = async () => {
    if (!segments.length) {
      toast.error('请先准备分段与素材')
      return
    }
    const payload: ScriptStockComposeSegmentApi[] = []
    for (const s of segments) {
      if (s.sourceTab === 'local') {
        if (!s.localVideoIds.length) {
          toast.error('存在未选择本地视频的段落')
          return
        }
        if (s.localVideoIds.length > 1 && audioMode !== 'tts_only') {
          toast.error('多段本地素材按顺序拼接仅支持「仅 TTS」；请改为单条或切换为仅 TTS。')
          return
        }
        const slotTrims =
          s.libraryTrimSlots ?? s.localVideoIds.map((id) => defaultLibraryTrimForVideo(libraryVideos, id))
        payload.push({
          kind: 'library',
          library_video_ids: s.localVideoIds,
          library_trims: slotTrims.map((t) => ({ in_sec: t.inSec, out_sec: t.outSec })),
          text: (s.text || '').trim(),
        })
      } else {
        if (!s.pexelsStoredRelPaths.length) {
          toast.error('存在未选用 Pexels 素材的段落（请先下载并在卡片上勾选，顺序为成片拼接顺序）')
          return
        }
        payload.push({
          kind: 'pexels',
          pexels_stored_rel_paths: s.pexelsStoredRelPaths,
          text: (s.text || '').trim(),
        })
      }
    }
    if ((audioMode === 'tts_only' || audioMode === 'mix') && payload.every((p) => !p.text)) {
      toast.error('当前模式需要配音文案：请在各段填写文案，或改用「仅素材原声」')
      return
    }
    setComposing(true)
    try {
      const res = await scriptStockApi.compose({
        segments: payload,
        project_name: projectName.trim() || 'stock_clip',
        audio_mode: audioMode,
        tts_volume_db: ttsVolumeDb,
        original_volume_db: originalVolumeDb,
        timeline_mode: timelineMode,
        video_extend_policy: videoExtendPolicy,
        material_tts_fill: materialTtsFill,
        material_tts_longer: materialTtsLonger,
        include_subtitle: subtitleEnabled,
        subtitle_style: subtitleEnabled ? (subtitleStyle ?? DEFAULT_SUBTITLE_STYLE) : undefined,
      })
      const base = API_BASE_URL.replace(/\/$/, '')
      const path = (res.public_url || '').startsWith('/') ? res.public_url : `/${res.public_url || ''}`
      const fullUrl = `${base}${path}`
      setLastComposeUrl(fullUrl)
      setLastComposeFilename(res.filename || null)
      toast.success('配音成片已完成，链接已显示在下方')
      window.open(fullUrl, '_blank', 'noopener,noreferrer')
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setComposing(false)
    }
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
            <Clapperboard className="w-4 h-4 text-sky-400" />
            文案素材成片
          </p>
          <p className="text-[11px] text-slate-500 leading-relaxed max-w-xl">
            为每一段匹配画面并合成<strong className="text-slate-300"> TTS 配音</strong>
            （下方可选仅配音 / 仅原声 / 混合及分贝调节）。本地与 <strong className="text-slate-300">Pexels</strong>{' '}
            均为卡片多选、角标为拼接顺序（与手动匹配一致）；<strong className="text-slate-300">Shift+点击</strong>
            可在同组内再叠一段相同素材。成片画面时长由下方「以配音为准 / 以素材为准」及延伸策略决定，始终使用所选素材的完整画面（无额外截取秒数）。
            Pexels 已下载会显示「已缓存」，可在上方缓存区管理删除。
          </p>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0 text-[11px]">
          <Link href="/settings" className="text-sky-400 hover:underline">
            Pexels API Key →
          </Link>
          <Link href="/settings" className="text-emerald-400/90 hover:underline">
            TTS 配音引擎 →
          </Link>
        </div>
      </div>

      <div className="rounded-xl border border-slate-700 bg-slate-950/40 p-4 space-y-3">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">AI 写文案（可选）</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="主题或关键词"
            className="sm:col-span-2 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500"
          />
          <input
            type="number"
            min={1}
            max={20}
            value={numParas}
            onChange={(e) => setNumParas(Math.max(1, Math.min(20, Number(e.target.value) || 5)))}
            className="rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500"
          />
        </div>
        <input
          value={styleHint}
          onChange={(e) => setStyleHint(e.target.value)}
          placeholder="风格补充（可选）：如 轻快短视频旁白、纪录片口吻…"
          className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500"
        />
        <button
          type="button"
          disabled={generatingScript}
          onClick={() => void handleGenerateScript()}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-medium"
        >
          {generatingScript ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
          AI 生成文案
        </button>
      </div>

      <div className="rounded-xl border border-slate-700 bg-slate-950/40 p-4 space-y-2">
        <div className="flex flex-wrap items-center gap-2 justify-between">
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">文案正文</p>
          <p className="text-[10px] text-slate-600 hidden sm:block">
            拆分后可拖拽段落排序，与手动匹配一致
          </p>
        </div>
        <textarea
          value={fullScript}
          onChange={(e) => setFullScript(e.target.value)}
          rows={8}
          placeholder="粘贴完整文案，或先用上方 AI 生成…"
          className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500 resize-y min-h-[140px]"
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={splitting}
            onClick={() => void handleSplit('paragraph')}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-600 hover:border-sky-500 text-sm text-slate-200"
          >
            {splitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Layers className="w-4 h-4 text-sky-400" />}
            按空行分段
          </button>
          <button
            type="button"
            disabled={splitting}
            onClick={() => void handleSplit('line')}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-600 hover:border-sky-500 text-sm text-slate-200"
          >
            {splitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <SplitSquareHorizontal className="w-4 h-4 text-sky-400" />}
            按单行分段
          </button>
          <button
            type="button"
            onClick={addSegment}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-700 bg-slate-800/40 hover:border-slate-500 text-xs text-slate-300"
          >
            <Plus className="w-3.5 h-3.5" />
            手动添加段落
          </button>
        </div>
      </div>

      {segments.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="space-y-0.5 min-w-0">
              <p className="text-xs font-semibold text-slate-400">
                分段素材（共 {segments.length} 段）
              </p>
              <p className="text-[10px] text-slate-600 hidden sm:block">
                可拖拽左侧手柄排序，或使用每段顶部箭头；支持新增、删除、清空
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={addSegment}
                className="text-xs px-3 py-1.5 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800 inline-flex items-center gap-1"
              >
                <Plus className="w-3.5 h-3.5" />
                添加段落
              </button>
              <button
                type="button"
                onClick={clearAllSegments}
                className="text-xs px-3 py-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-500/10"
              >
                清空全部
              </button>
              <button
                type="button"
                disabled={suggesting}
                onClick={() => void handleSuggestAllQueries()}
                className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600/80 hover:bg-indigo-500 text-white disabled:opacity-50"
              >
                {suggesting ? <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1" /> : null}
                一键生成英文搜索词
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-950/50 p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-semibold text-slate-400">Pexels 本地下载缓存</p>
              <button
                type="button"
                disabled={pexelsCacheLoading}
                onClick={() => void loadPexelsCache()}
                className="text-xs px-3 py-1.5 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
              >
                {pexelsCacheLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1" /> : null}
                刷新列表
              </button>
            </div>
            {pexelsCacheItems.length === 0 ? (
              <p className="text-[11px] text-slate-500">暂无已下载文件。搜索并下载后此处会列出，可删除释放磁盘。</p>
            ) : (
              <ul className="max-h-44 overflow-y-auto space-y-1.5 pr-1">
                {pexelsCacheItems.map((it) => (
                  <li
                    key={it.stored_rel_path}
                    className="flex items-center gap-2 rounded-lg bg-slate-900/80 border border-slate-700/80 px-2 py-1.5 text-[11px]"
                  >
                    <span className="min-w-0 flex-1 truncate text-slate-300" title={it.stored_rel_path}>
                      ID {it.pexels_video_id || '?'} · {it.filename} · {fmtBytes(it.size_bytes)}
                    </span>
                    <button
                      type="button"
                      onClick={() => void handleDeletePexelsCache(it.stored_rel_path)}
                      className="shrink-0 p-1.5 rounded text-rose-400 hover:bg-rose-500/15 hover:text-rose-300"
                      title="从本机删除"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[10px] text-slate-500 leading-relaxed">
              已缓存的视频在下方结果卡片上会显示「已缓存」，可直接点卡片勾选进成片，无需重复下载。删除文件后各段已勾选的该路径会自动取消。
            </p>
          </div>

          <div className="space-y-4">
            {segments.map((seg, idx) => {
              const canUp = idx > 0
              const canDown = segments.length > 0 && idx < segments.length - 1
              return (
              <div
                key={seg.id}
                className={[
                  'rounded-2xl transition-[opacity,box-shadow] duration-200',
                  draggingId === seg.id ? 'opacity-45' : '',
                  draggingId && draggingId !== seg.id && dropTargetId === seg.id
                    ? 'ring-2 ring-indigo-400/90 shadow-[0_0_0_1px_rgba(129,140,248,0.35),0_8px_28px_-6px_rgba(99,102,241,0.45)]'
                    : '',
                  flashId === seg.id
                    ? 'ring-2 ring-emerald-400 shadow-[0_0_24px_-4px_rgba(52,211,153,0.55)]'
                    : '',
                ].join(' ')}
                onDragOver={(e) => {
                  if (!draggingId || draggingId === seg.id) return
                  e.preventDefault()
                  e.dataTransfer.dropEffect = 'move'
                  setDropTargetId(seg.id)
                }}
                onDragLeave={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node)) setDropTargetId(null)
                }}
                onDrop={(e) => {
                  e.preventDefault()
                  const fromId =
                    e.dataTransfer.getData(STOCK_SEG_DRAG_MIME) || e.dataTransfer.getData('text/plain')
                  setDropTargetId(null)
                  setDraggingId(null)
                  if (!fromId || fromId === seg.id) return
                  moveStockSegment(fromId, seg.id)
                  flashRow(fromId)
                }}
              >
              <div className="rounded-xl border border-slate-700 bg-slate-950/50 overflow-hidden">
                <div className="flex items-center gap-2 px-3 py-2.5 bg-slate-900/60 border-b border-slate-800">
                  <div
                    role="button"
                    tabIndex={0}
                    title="拖动排序"
                    aria-label="拖动排序"
                    className="shrink-0 p-0.5 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 cursor-grab active:cursor-grabbing touch-none select-none"
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData(STOCK_SEG_DRAG_MIME, seg.id)
                      e.dataTransfer.setData('text/plain', seg.id)
                      e.dataTransfer.effectAllowed = 'move'
                      setDraggingId(seg.id)
                      setDropTargetId(null)
                    }}
                    onDragEnd={() => {
                      setDraggingId(null)
                      setDropTargetId(null)
                    }}
                  >
                    <GripVertical className="w-4 h-4" />
                  </div>
                  <div className="w-6 h-6 rounded-lg bg-sky-500/20 text-sky-300 text-xs font-bold flex items-center justify-center shrink-0">
                    {idx + 1}
                  </div>
                  <span className="text-xs text-slate-400 font-medium">段落 {idx + 1}</span>
                  <div className="flex-1 min-w-0" />
                  {segments.length > 1 ? (
                    <div className="flex items-center gap-0.5 shrink-0 rounded-lg border border-slate-700/80 bg-slate-900/50 p-0.5">
                      <button
                        type="button"
                        title="移至顶部"
                        disabled={!canUp}
                        onClick={() => moveSegmentRel(seg.id, 'top')}
                        className="p-1 rounded-md text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-25 disabled:hover:bg-transparent transition-colors"
                      >
                        <ChevronsUp className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        title="上移"
                        disabled={!canUp}
                        onClick={() => moveSegmentRel(seg.id, 'up')}
                        className="p-1 rounded-md text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-25 disabled:hover:bg-transparent transition-colors"
                      >
                        <ChevronUp className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        title="下移"
                        disabled={!canDown}
                        onClick={() => moveSegmentRel(seg.id, 'down')}
                        className="p-1 rounded-md text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-25 disabled:hover:bg-transparent transition-colors"
                      >
                        <ChevronDown className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        title="移至底部"
                        disabled={!canDown}
                        onClick={() => moveSegmentRel(seg.id, 'bottom')}
                        className="p-1 rounded-md text-slate-500 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-25 disabled:hover:bg-transparent transition-colors"
                      >
                        <ChevronsDown className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ) : null}
                  <button
                    type="button"
                    title="删除本段"
                    onClick={() => removeSegment(seg.id)}
                    className="shrink-0 p-1 rounded-md text-slate-600 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                <div className="p-4 space-y-3">
                <div className="space-y-1.5">
                  <p className="text-[11px] text-slate-500">配音文案（可改）</p>
                  <textarea
                    value={seg.text}
                    onChange={(e) =>
                      setSegments((prev) =>
                        prev.map((s) => (s.id === seg.id ? { ...s, text: e.target.value } : s)),
                      )
                    }
                    rows={3}
                    placeholder="该段口播/旁白，将用于 TTS…"
                    className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500 resize-y min-h-[72px]"
                  />
                </div>

                <div className="flex rounded-lg border border-slate-700 overflow-hidden w-fit">
                  <button
                    type="button"
                    onClick={() =>
                      setSegments((prev) => prev.map((s) => (s.id === seg.id ? { ...s, sourceTab: 'local' } : s)))
                    }
                    className={`px-3 py-1.5 text-xs font-medium ${
                      seg.sourceTab === 'local' ? 'bg-violet-600 text-white' : 'bg-slate-900 text-slate-400'
                    }`}
                  >
                    本地素材库
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setSegments((prev) => prev.map((s) => (s.id === seg.id ? { ...s, sourceTab: 'pexels' } : s)))
                    }
                    className={`px-3 py-1.5 text-xs font-medium ${
                      seg.sourceTab === 'pexels' ? 'bg-sky-600 text-white' : 'bg-slate-900 text-slate-400'
                    }`}
                  >
                    Pexels
                  </button>
                </div>

                {seg.sourceTab === 'local' ? (
                  <div className="space-y-3">
                    <p className="text-[10px] text-slate-500">
                      本段独立搜索、分页；点击卡片勾选或取消。<strong className="text-slate-400">Shift+点击</strong>
                      可叠同素材。多条拼接仅「仅 TTS」模式可用。
                    </p>
                    <SegmentLocalLibraryBlock
                      localVideoIds={seg.localVideoIds}
                      onToggleVideo={(videoId, e) => toggleLocalVideo(seg.id, videoId, e)}
                      onListItems={mergeLibraryListItems}
                    />
                    {seg.localVideoIds.length > 0 ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setTrimDialogSegId(seg.id)}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-600 hover:border-violet-500 text-[11px] text-slate-200 transition-colors"
                        >
                          <Scissors className="w-3.5 h-3.5 shrink-0" />
                          自选区间（时间轴）
                        </button>
                        {seg.localVideoIds.some((vid, i) =>
                          libraryTrimSlotIsCustom(
                            libraryVideos,
                            vid,
                            seg.libraryTrimSlots?.[i] ?? defaultLibraryTrimForVideo(libraryVideos, vid),
                          ),
                        ) ? (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-300 border border-violet-500/35">
                            已裁切
                          </span>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex flex-wrap gap-2">
                      <input
                        value={seg.searchQuery}
                        onChange={(e) =>
                          setSegments((prev) =>
                            prev.map((s) => (s.id === seg.id ? { ...s, searchQuery: e.target.value } : s)),
                          )
                        }
                        placeholder="英文搜索词，如 ocean sunset"
                        className="flex-1 min-w-[160px] rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200"
                      />
                      <button
                        type="button"
                        disabled={seg.searching}
                        onClick={() => void searchPexelsForSeg(seg.id)}
                        className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 border border-slate-600 hover:border-sky-500 text-sm"
                      >
                        {seg.searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                        搜索
                      </button>
                    </div>
                    {seg.pexelsStoredRelPaths.length > 0 ? (
                      <p className="text-[11px] text-emerald-400 flex flex-wrap items-center gap-1">
                        <Film className="w-3.5 h-3.5 shrink-0" />
                        本段已选 {seg.pexelsStoredRelPaths.length} 个文件（顺序已标号）
                      </p>
                    ) : (
                      <p className="text-[11px] text-slate-500">
                        已缓存的点卡片勾选（<strong className="text-slate-400">Shift+点击</strong>
                        再叠同文件）；未缓存的先「下载」并追加到顺序。
                      </p>
                    )}
                    <div className="flex gap-3 overflow-x-auto pb-2 -mx-1 px-1">
                      {seg.pexelsResults.map((pv) => {
                        const cachedRel = bestCachedRelForPexelsId(pexelsCacheItems, pv.id)
                        const cached = Boolean(cachedRel)
                        const positions =
                          cachedRel != null && cached
                            ? orderPositionsForKey(seg.pexelsStoredRelPaths, cachedRel)
                            : []
                        if (!cached) {
                          return (
                            <OrderedPickCard
                              key={pv.id}
                              imageUrl={pv.image}
                              title={`${pv.duration}s`}
                              subtitle="未下载"
                              orderPositions={[]}
                              selected={false}
                              disabled
                              onClick={() => {}}
                              footer={
                                <div className="px-2 pb-2">
                                  <button
                                    type="button"
                                    disabled={seg.downloadingId === pv.id}
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      void downloadPexels(seg.id, pv.id)
                                    }}
                                    className="w-full flex items-center justify-center gap-1 py-1.5 rounded bg-sky-700 hover:bg-sky-600 text-[11px] text-white disabled:opacity-50"
                                  >
                                    {seg.downloadingId === pv.id ? (
                                      <Loader2 className="w-3 h-3 animate-spin" />
                                    ) : (
                                      <Download className="w-3 h-3" />
                                    )}
                                    下载
                                  </button>
                                </div>
                              }
                            />
                          )
                        }
                        return (
                          <OrderedPickCard
                            key={pv.id}
                            imageUrl={pv.image}
                            title={`${pv.duration}s`}
                            subtitle="已缓存 · 点击勾选（Shift+再叠一段）"
                            orderPositions={positions}
                            selected={positions.length > 0}
                            onClick={(e) => cachedRel && togglePexelsRel(seg.id, cachedRel, e)}
                          />
                        )
                      })}
                    </div>
                  </div>
                )}
                </div>
              </div>
              </div>
              )
            })}
          </div>

          <div className="rounded-xl border border-emerald-500/25 bg-emerald-950/30 p-4 space-y-4">
            <div className="flex items-start gap-2">
              <Mic className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
              <div className="space-y-1 min-w-0">
                <p className="text-xs font-semibold text-emerald-200">配音与混音</p>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  <strong className="text-slate-400">仅 TTS</strong>：画面素材静音，只保留配音（默认）。
                  <strong className="text-slate-400"> 仅原声</strong>：保留素材里的录音，不做 TTS。
                  <strong className="text-slate-400"> 混合</strong>：TTS 与素材原声叠加，可用下方两个音量分别精细调节。
                  Pexels 素材多为环境声或无对白，混合时建议压低「原声」。
                </p>
                <p className="text-[10px] text-slate-500 leading-relaxed border-t border-slate-700/50 pt-2 mt-2">
                  <strong className="text-slate-400">字幕</strong>：
                  {subtitleEnabled
                    ? '侧栏已开启「字幕成片」，合成时将按各段配音文案与分段时长硬烧字幕（样式与侧栏字幕一致）。'
                    : '侧栏关闭「字幕成片」时不会烧录字幕；需要字幕请在侧栏打开字幕成片。'}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {(
                [
                  { id: 'tts_only' as const, label: '仅 TTS 配音' },
                  { id: 'original_only' as const, label: '仅素材原声' },
                  { id: 'mix' as const, label: 'TTS + 原声混合' },
                ]
              ).map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setAudioMode(id)}
                  className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                    audioMode === id
                      ? 'bg-emerald-600 text-white'
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-700 border border-slate-700'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {(audioMode === 'tts_only' || audioMode === 'mix') && (
              <div className="space-y-3 rounded-lg border border-slate-700/80 bg-slate-950/50 p-3">
                <p className="text-[11px] font-medium text-slate-200">画面与配音时长</p>
                <p className="text-[10px] text-slate-500 leading-relaxed">
                  与手动匹配成片逻辑对齐：<strong className="text-slate-400">以配音为准</strong>
                  时整段时长跟 TTS（短则裁画面、长则补画面）；<strong className="text-slate-400">以素材为准</strong>
                  时整段时长跟素材画面，TTS 在轨上补齐或压缩。
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setTimelineMode('follow_narration')}
                    className={`px-3 py-1.5 rounded-lg text-[11px] font-medium ${
                      timelineMode === 'follow_narration'
                        ? 'bg-sky-600 text-white'
                        : 'bg-slate-800 text-slate-400 border border-slate-700'
                    }`}
                  >
                    以配音为准（推荐）
                  </button>
                  <button
                    type="button"
                    onClick={() => setTimelineMode('follow_material')}
                    className={`px-3 py-1.5 rounded-lg text-[11px] font-medium ${
                      timelineMode === 'follow_material'
                        ? 'bg-sky-600 text-white'
                        : 'bg-slate-800 text-slate-400 border border-slate-700'
                    }`}
                  >
                    以素材成片为准
                  </button>
                </div>
                {timelineMode === 'follow_narration' && (
                  <div className="space-y-1.5">
                    <p className="text-[10px] text-slate-500">配音长于画面时</p>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => setVideoExtendPolicy('loop_video_to_cover')}
                        className={`px-3 py-1.5 rounded-lg text-[11px] ${
                          videoExtendPolicy === 'loop_video_to_cover'
                            ? 'bg-indigo-600 text-white'
                            : 'bg-slate-800 text-slate-400 border border-slate-700'
                        }`}
                      >
                        循环拼接画面
                      </button>
                      <button
                        type="button"
                        onClick={() => setVideoExtendPolicy('freeze_last_frame')}
                        className={`px-3 py-1.5 rounded-lg text-[11px] ${
                          videoExtendPolicy === 'freeze_last_frame'
                            ? 'bg-indigo-600 text-white'
                            : 'bg-slate-800 text-slate-400 border border-slate-700'
                        }`}
                      >
                        尾帧定格
                      </button>
                    </div>
                  </div>
                )}
                {timelineMode === 'follow_material' && (
                  <div className="space-y-2 border-t border-slate-700/60 pt-2">
                    <div className="space-y-1">
                      <p className="text-[10px] text-slate-500">TTS 短于画面时</p>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => setMaterialTtsFill('pad_silence')}
                          className={`px-3 py-1.5 rounded-lg text-[11px] ${
                            materialTtsFill === 'pad_silence'
                              ? 'bg-violet-600 text-white'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          尾段补静音
                        </button>
                        <button
                          type="button"
                          onClick={() => setMaterialTtsFill('loop_audio')}
                          className={`px-3 py-1.5 rounded-lg text-[11px] ${
                            materialTtsFill === 'loop_audio'
                              ? 'bg-violet-600 text-white'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          循环该段 TTS
                        </button>
                      </div>
                    </div>
                    <div className="space-y-1">
                      <p className="text-[10px] text-slate-500">TTS 长于画面时</p>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => setMaterialTtsLonger('stretch_audio')}
                          className={`px-3 py-1.5 rounded-lg text-[11px] ${
                            materialTtsLonger === 'stretch_audio'
                              ? 'bg-violet-600 text-white'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          变速压缩配音
                        </button>
                        <button
                          type="button"
                          onClick={() => setMaterialTtsLonger('trim_tts')}
                          className={`px-3 py-1.5 rounded-lg text-[11px] ${
                            materialTtsLonger === 'trim_tts'
                              ? 'bg-violet-600 text-white'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          裁掉多余配音
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
            {(audioMode === 'tts_only' || audioMode === 'mix') && (
              <div className="space-y-1">
                <div className="flex justify-between text-[11px] text-slate-400">
                  <span>TTS 配音音量</span>
                  <span className="tabular-nums text-emerald-300">{ttsVolumeDb} dB</span>
                </div>
                <input
                  type="range"
                  min={-24}
                  max={12}
                  step={1}
                  value={ttsVolumeDb}
                  onChange={(e) => setTtsVolumeDb(Number(e.target.value))}
                  className="w-full accent-emerald-500"
                />
              </div>
            )}
            {(audioMode === 'original_only' || audioMode === 'mix') && (
              <div className="space-y-1">
                <div className="flex justify-between text-[11px] text-slate-400">
                  <span>素材原声音量</span>
                  <span className="tabular-nums text-violet-300">{originalVolumeDb} dB</span>
                </div>
                <input
                  type="range"
                  min={-48}
                  max={12}
                  step={1}
                  value={originalVolumeDb}
                  onChange={(e) => setOriginalVolumeDb(Number(e.target.value))}
                  className="w-full accent-violet-500"
                />
              </div>
            )}
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-950/40 p-4 flex flex-col sm:flex-row gap-3 sm:items-end">
            <div className="flex-1 space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-wider">成片文件名前缀</label>
              <input
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200"
              />
            </div>
            <button
              type="button"
              disabled={composing}
              onClick={() => void handleCompose()}
              className="px-6 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 text-white text-sm font-semibold shrink-0"
            >
              {composing ? <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> : null}
              合成配音成片
            </button>
          </div>
        </div>
      )}

      {lastComposeUrl ? (
        <div className="rounded-xl border border-emerald-500/35 bg-emerald-950/15 p-4 space-y-2">
          <p className="text-[11px] font-medium text-emerald-200/95">
            本次成片访问链接（弹窗被拦截或未打开时，可从此复制或点击打开）
          </p>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch">
            <input
              readOnly
              value={lastComposeUrl}
              onFocus={(e) => e.target.select()}
              className="flex-1 min-w-0 rounded-md bg-slate-950 border border-slate-600 px-2 py-2 text-[11px] font-mono text-slate-300"
            />
            <div className="flex gap-2 shrink-0">
              <button
                type="button"
                onClick={() => {
                  void (async () => {
                    try {
                      await navigator.clipboard.writeText(lastComposeUrl)
                      toast.success('链接已复制到剪贴板')
                    } catch {
                      toast.error('复制失败，请手动框选输入框内链接')
                    }
                  })()
                }}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 border border-slate-600 text-[11px] text-slate-200 hover:bg-slate-700"
              >
                <Copy className="w-3.5 h-3.5" />
                复制
              </button>
              <a
                href={lastComposeUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-700/90 hover:bg-emerald-600 text-[11px] text-white"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                打开
              </a>
            </div>
          </div>
          {lastComposeFilename ? (
            <p className="text-[10px] text-slate-500">文件名：{lastComposeFilename}</p>
          ) : null}
        </div>
      ) : null}

      <StockLibraryTrimDialog
        open={trimDialogSegId !== null && !!trimDialogSeg?.localVideoIds.length}
        onClose={() => setTrimDialogSegId(null)}
        videoIdsOrdered={trimDialogSeg?.localVideoIds ?? []}
        videos={libraryVideos}
        initialSlots={trimDialogInitialSlots}
        onSave={(slots) => {
          const id = trimDialogSegId
          if (!id) return
          setSegments((prev) => prev.map((s) => (s.id === id ? { ...s, libraryTrimSlots: slots } : s)))
          setTrimDialogSegId(null)
        }}
      />
    </div>
  )
}
