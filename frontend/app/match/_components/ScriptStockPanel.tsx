'use client'

import { createPortal } from 'react-dom'
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
  X,
} from 'lucide-react'
import type { Video } from '@/lib/api'
import {
  API_BASE_URL,
  formatFastApiDetail,
  scriptStockApi,
  type ScriptStockAudioMode,
  type ScriptStockMaterialTtsFill,
  type ScriptStockMaterialTtsLonger,
  type ScriptStockOnlineProvider,
  type ScriptStockPexelsCacheItemApi,
  type ScriptStockPixabayCacheItemApi,
  type ScriptStockUnsplashCacheItemApi,
  type ScriptStockTimelineMode,
  type BgmMixConfigApi,
  type ScriptStockComposeSegmentApi,
  type ScriptStockVideoExtendPolicy,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'
import { useTaskStore } from '@/lib/task-store'
import { fetchSSE } from '@/lib/stream'
import { VoiceInputControl } from '@/components/ui/voice-input'
import { toastRecommendJianyingParentDir } from '@/lib/jianying-parent-dir-hint'
import { useConfirm } from '@/hooks/use-confirm'
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
import { StockOnlineCachePanel } from './StockOnlineCachePanel'
import { AutoEditBgmMixPanel } from './AutoEditBgmMixPanel'
import { useAutoEditBgmTracks } from './autoEditPanelHooks'
import {
  downloadKey,
  newStockSeg,
  onlineProviderLabel,
  storedRelPathsForProvider,
  type StockSegState,
} from './stockOnlineTypes'

function bestCachedRelForId(
  provider: ScriptStockOnlineProvider,
  items: ScriptStockPexelsCacheItemApi[] | ScriptStockPixabayCacheItemApi[] | ScriptStockUnsplashCacheItemApi[],
  mediaId: string | number,
  mediaType: 'image' | 'video',
): string | undefined {
  const hits = items.filter((it) => {
    const mt =
      (it as { media_type?: string }).media_type ||
      (/\.(jpe?g|png|webp|gif|bmp)$/i.test(it.filename) ? 'image' : 'video')
    if (mt !== mediaType) return false
    if (provider === 'pexels') return (it as ScriptStockPexelsCacheItemApi).pexels_video_id === mediaId
    if (provider === 'pixabay') return (it as ScriptStockPixabayCacheItemApi).pixabay_video_id === mediaId
    return String((it as ScriptStockUnsplashCacheItemApi).unsplash_photo_id) === String(mediaId)
  })
  if (!hits.length) return undefined
  hits.sort((a, b) => b.mtime - a.mtime)
  return hits[0].stored_rel_path
}

/** 本机已下载 Pexels（storage 相对路径）→ 浏览器可 `<video src>` 的同源 URL */
function storageBrowserVideoUrl(storedRelPath: string): string {
  const r = (storedRelPath || '').replace(/\\/g, '/').replace(/^\/+/, '')
  const webPath = r.startsWith('storage/') ? `/${r}` : `/storage/${r}`
  const base = API_BASE_URL.replace(/\/$/, '')
  return base ? `${base}${webPath}` : webPath
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
  const confirm = useConfirm()
  const taskStoreUpsert = useTaskStore((s) => s.upsert)
  const taskStorePatch = useTaskStore((s) => s.patch)
  const { bgmTracks, bgmListError } = useAutoEditBgmTracks()
  const [stockBgmEnabled, setStockBgmEnabled] = useState(false)
  const [stockBgmTrackId, setStockBgmTrackId] = useState('')
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
  const [jianyingExporting, setJianyingExporting] = useState(false)
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
  const [pixabayCacheItems, setPixabayCacheItems] = useState<ScriptStockPixabayCacheItemApi[]>([])
  const [unsplashCacheItems, setUnsplashCacheItems] = useState<ScriptStockUnsplashCacheItemApi[]>([])
  const [cacheLoading, setCacheLoading] = useState<Record<ScriptStockOnlineProvider, boolean>>({
    pexels: false,
    pixabay: false,
    unsplash: false,
  })
  const [cacheClearing, setCacheClearing] = useState<Record<ScriptStockOnlineProvider, boolean>>({
    pexels: false,
    pixabay: false,
    unsplash: false,
  })
  const [pexelsPreviewUrl, setPexelsPreviewUrl] = useState<string | null>(null)
  const pexelsPreviewVideoRef = useRef<HTMLVideoElement>(null)

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
    setSegments((prev) => [...prev, newStockSeg('')])
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

  const loadOnlineCache = useCallback(async (provider: ScriptStockOnlineProvider) => {
    setCacheLoading((p) => ({ ...p, [provider]: true }))
    try {
      if (provider === 'pexels') {
        const res = await scriptStockApi.pexelsListCache()
        setPexelsCacheItems(res.items || [])
      } else if (provider === 'pixabay') {
        const res = await scriptStockApi.pixabayListCache()
        setPixabayCacheItems(res.items || [])
      } else {
        const res = await scriptStockApi.unsplashListCache()
        setUnsplashCacheItems(res.items || [])
      }
    } catch {
      if (provider === 'pexels') setPexelsCacheItems([])
      else if (provider === 'pixabay') setPixabayCacheItems([])
      else setUnsplashCacheItems([])
    } finally {
      setCacheLoading((p) => ({ ...p, [provider]: false }))
    }
  }, [])

  const loadAllOnlineCaches = useCallback(async () => {
    await Promise.all([
      loadOnlineCache('pexels'),
      loadOnlineCache('pixabay'),
      loadOnlineCache('unsplash'),
    ])
  }, [loadOnlineCache])

  useEffect(() => {
    void loadAllOnlineCaches()
  }, [loadAllOnlineCaches])

  const closePexelsPreview = useCallback(() => {
    setPexelsPreviewUrl(null)
    const v = pexelsPreviewVideoRef.current
    if (v) {
      v.pause()
      v.currentTime = 0
    }
  }, [])

  useEffect(() => {
    if (!pexelsPreviewUrl) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closePexelsPreview()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pexelsPreviewUrl, closePexelsPreview])

  const clearSegPathsForProvider = (provider: ScriptStockOnlineProvider) => {
    setSegments((prev) =>
      prev.map((s) => {
        if (provider === 'pexels') return { ...s, pexelsStoredRelPaths: [] }
        if (provider === 'pixabay') return { ...s, pixabayStoredRelPaths: [] }
        return { ...s, unsplashStoredRelPaths: [] }
      }),
    )
  }

  const removeSegPath = (provider: ScriptStockOnlineProvider, storedRelPath: string) => {
    setSegments((prev) =>
      prev.map((s) => {
        if (provider === 'pexels') {
          return { ...s, pexelsStoredRelPaths: s.pexelsStoredRelPaths.filter((p) => p !== storedRelPath) }
        }
        if (provider === 'pixabay') {
          return { ...s, pixabayStoredRelPaths: s.pixabayStoredRelPaths.filter((p) => p !== storedRelPath) }
        }
        return { ...s, unsplashStoredRelPaths: s.unsplashStoredRelPaths.filter((p) => p !== storedRelPath) }
      }),
    )
  }

  const handleClearOnlineCache = async (provider: ScriptStockOnlineProvider) => {
    const label = onlineProviderLabel(provider)
    const ok = await confirm({
      title: `清空全部 ${label} 本地下载？`,
      description: `将删除 stock_media/${provider} 内所有已下载文件，不可恢复；各段落已勾选的 ${label} 素材也会被取消。`,
      variant: 'danger',
      confirmLabel: '确定清空',
      cancelLabel: '取消',
    })
    if (!ok) return
    setCacheClearing((p) => ({ ...p, [provider]: true }))
    try {
      const res =
        provider === 'pexels'
          ? await scriptStockApi.pexelsClearCache()
          : provider === 'pixabay'
            ? await scriptStockApi.pixabayClearCache()
            : await scriptStockApi.unsplashClearCache()
      const n = Number(res.deleted_files) || 0
      toast.success(n > 0 ? `已清空 ${n} 个 ${label} 缓存文件` : '缓存目录已为空')
      if (provider === 'pexels') setPexelsCacheItems([])
      else if (provider === 'pixabay') setPixabayCacheItems([])
      else setUnsplashCacheItems([])
      clearSegPathsForProvider(provider)
      await loadOnlineCache(provider)
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setCacheClearing((p) => ({ ...p, [provider]: false }))
    }
  }

  const handleDeleteOnlineCache = async (provider: ScriptStockOnlineProvider, storedRelPath: string) => {
    try {
      if (provider === 'pexels') await scriptStockApi.pexelsDeleteFile({ stored_rel_path: storedRelPath })
      else if (provider === 'pixabay') await scriptStockApi.pixabayDeleteFile({ stored_rel_path: storedRelPath })
      else await scriptStockApi.unsplashDeleteFile({ stored_rel_path: storedRelPath })
      toast.success('已从本机删除该文件')
      if (provider === 'pexels') {
        setPexelsCacheItems((prev) => prev.filter((i) => i.stored_rel_path !== storedRelPath))
      } else if (provider === 'pixabay') {
        setPixabayCacheItems((prev) => prev.filter((i) => i.stored_rel_path !== storedRelPath))
      } else {
        setUnsplashCacheItems((prev) => prev.filter((i) => i.stored_rel_path !== storedRelPath))
      }
      removeSegPath(provider, storedRelPath)
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

  const toggleOnlineRel = (
    segId: string,
    provider: ScriptStockOnlineProvider,
    rel: string,
    e: MouseEvent,
  ) => {
    if (!rel) return
    setSegments((prev) =>
      prev.map((s) => {
        if (s.id !== segId) return s
        const cur = storedRelPathsForProvider(s, provider)
        const next = e.shiftKey ? appendIdToOrderedList(cur, rel) : toggleIdInOrderedList(cur, rel)
        if (provider === 'pexels') return { ...s, pexelsStoredRelPaths: next, sourceTab: provider }
        if (provider === 'pixabay') return { ...s, pixabayStoredRelPaths: next, sourceTab: provider }
        return { ...s, unsplashStoredRelPaths: next, sourceTab: provider }
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
      const segs = (res.segments || []).map((t) => newStockSeg(t))
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

  const searchOnlineForSeg = async (segId: string, provider: ScriptStockOnlineProvider) => {
    const seg = segments.find((s) => s.id === segId)
    if (!seg) return
    const q = (seg.searchQuery || seg.text).trim()
    if (!q) {
      toast.error('请填写搜索词')
      return
    }
    setSegments((prev) =>
      prev.map((s) => (s.id === segId ? { ...s, searching: true, sourceTab: provider } : s)),
    )
    try {
      if (provider === 'pexels') {
        const res = await scriptStockApi.pexelsSearch({ query: q, per_page: 12 })
        setSegments((prev) =>
          prev.map((s) =>
            s.id === segId
              ? {
                  ...s,
                  searching: false,
                  pexelsResults: res.videos || [],
                  pexelsImageResults: res.images || [],
                }
              : s,
          ),
        )
      } else if (provider === 'pixabay') {
        const res = await scriptStockApi.pixabaySearch({ query: q, per_page: 12 })
        setSegments((prev) =>
          prev.map((s) =>
            s.id === segId
              ? {
                  ...s,
                  searching: false,
                  pixabayResults: res.videos || [],
                  pixabayImageResults: res.images || [],
                }
              : s,
          ),
        )
      } else {
        const res = await scriptStockApi.unsplashSearch({ query: q, per_page: 12 })
        setSegments((prev) =>
          prev.map((s) =>
            s.id === segId ? { ...s, searching: false, unsplashResults: res.photos || [] } : s,
          ),
        )
      }
    } catch (e) {
      setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, searching: false } : s)))
      toast.error(formatFastApiDetail(e))
    }
  }

  const downloadOnline = async (
    segId: string,
    provider: ScriptStockOnlineProvider,
    mediaType: 'image' | 'video',
    mediaId: string | number,
  ) => {
    const seg = segments.find((s) => s.id === segId)
    const search_query = ((seg?.searchQuery || seg?.text) || '').trim()
    const dkey = downloadKey(provider, mediaType, mediaId)
    setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, downloadingKey: dkey } : s)))
    try {
      let rel = ''
      if (provider === 'pexels') {
        const res = await scriptStockApi.pexelsDownload({
          pexels_media_id: Number(mediaId),
          media_type: mediaType,
          preferred_quality: 'hd',
          search_query: search_query || undefined,
        })
        rel = res.stored_rel_path
      } else if (provider === 'pixabay') {
        const res = await scriptStockApi.pixabayDownload({
          pixabay_media_id: Number(mediaId),
          media_type: mediaType,
          preferred_quality: mediaType === 'image' ? 'large' : 'medium',
          search_query: search_query || undefined,
        })
        rel = res.stored_rel_path
      } else {
        const res = await scriptStockApi.unsplashDownload({
          unsplash_photo_id: String(mediaId),
          search_query: search_query || undefined,
        })
        rel = res.stored_rel_path
      }
      await loadOnlineCache(provider)
      setSegments((prev) =>
        prev.map((s) => {
          if (s.id !== segId) return s
          const base = { ...s, downloadingKey: null, sourceTab: provider }
          if (provider === 'pexels') {
            return { ...base, pexelsStoredRelPaths: appendIdToOrderedList(s.pexelsStoredRelPaths, rel) }
          }
          if (provider === 'pixabay') {
            return { ...base, pixabayStoredRelPaths: appendIdToOrderedList(s.pixabayStoredRelPaths, rel) }
          }
          return { ...base, unsplashStoredRelPaths: appendIdToOrderedList(s.unsplashStoredRelPaths, rel) }
        }),
      )
      toast.success('已下载并追加到本段顺序（Shift+点击可再叠同一条）')
    } catch (e) {
      setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, downloadingKey: null } : s)))
      toast.error(formatFastApiDetail(e))
    }
  }

  function buildComposePayload(): ScriptStockComposeSegmentApi[] | null {
    if (!segments.length) {
      toast.error('请先准备分段与素材')
      return null
    }
    const payload: ScriptStockComposeSegmentApi[] = []
    for (const s of segments) {
      if (s.sourceTab === 'local') {
        if (!s.localVideoIds.length) {
          toast.error('存在未选择本地视频的段落')
          return null
        }
        if (s.localVideoIds.length > 1 && audioMode !== 'tts_only') {
          toast.error('多段本地素材按顺序拼接仅支持「仅 TTS」；请改为单条或切换为仅 TTS。')
          return null
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
        const provider = s.sourceTab as ScriptStockOnlineProvider
        const rels = storedRelPathsForProvider(s, provider)
        if (!rels.length) {
          toast.error(
            `存在未选用 ${onlineProviderLabel(provider)} 素材的段落（请先下载并在卡片上勾选）`,
          )
          return null
        }
        const row: ScriptStockComposeSegmentApi = {
          kind: provider,
          text: (s.text || '').trim(),
        }
        if (provider === 'pexels') row.pexels_stored_rel_paths = rels
        else if (provider === 'pixabay') row.pixabay_stored_rel_paths = rels
        else row.unsplash_stored_rel_paths = rels
        payload.push(row)
      }
    }
    if ((audioMode === 'tts_only' || audioMode === 'mix') && payload.every((p) => !p.text)) {
      toast.error('当前模式需要配音文案：请在各段填写文案，或改用「仅素材原声」')
      return null
    }
    return payload
  }

  const buildStockBgmPayload = (): BgmMixConfigApi | undefined => {
    const tid = stockBgmTrackId.trim()
    if (!stockBgmEnabled || !tid) return undefined
    return {
      enabled: true,
      track_id: tid,
      track_ids: [tid],
      volume_db: -12,
      loop: true,
      fade_in_sec: 0.8,
      fade_out_sec: 1.0,
    }
  }

  const handleCompose = async () => {
    const payload = buildComposePayload()
    if (!payload) return
    if (stockBgmEnabled && !stockBgmTrackId.trim()) {
      toast.error('已开启 BGM 混音，请选择一首背景音乐')
      return
    }
    setComposing(true)
    const taskHandle = toast.task('正在合成文案成片...')
    let jobId = ''
    try {
      const created = await scriptStockApi.compose({
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
        bgm: buildStockBgmPayload(),
      })
      jobId = created.job_id
      const streamUrl = (created.stream_url || '').startsWith('/')
        ? `${API_BASE_URL}${created.stream_url}`
        : created.stream_url || `/api/jobs/${jobId}/stream`

      taskStoreUpsert({
        id: jobId, title: '文案成片', kind: 'script_stock_compose', status: 'running',
        percent: null, logs: [], elapsedSec: 0, createdAt: Date.now(),
      })

      await fetchSSE(streamUrl, undefined, {
        onEvent(event, data) {
          if (event === 'result') {
            const r = data as { filename?: string; public_url?: string }
            let fullUrl = ''
            if (r?.public_url) {
              const base = API_BASE_URL.replace(/\/$/, '')
              const path = r.public_url.startsWith('/') ? r.public_url : `/${r.public_url}`
              fullUrl = `${base}${path}`
              setLastComposeUrl(fullUrl)
              setLastComposeFilename(r.filename || null)
            }
            taskHandle.done('文案成片已完成')
            taskStorePatch(jobId, {
              status: 'done',
              percent: 100,
              resultLabel: r?.filename || '文案成片已完成',
              result: fullUrl ? { filename: r.filename, url: fullUrl } : (data as Record<string, unknown>),
            })
            setComposing(false)
          }
          if (event === 'failed') {
            const f = data as { message?: string }
            const msg = f?.message || '文案成片失败'
            toast.error(msg)
            taskHandle.fail(msg)
            taskStorePatch(jobId, { status: 'error', error: msg })
            setComposing(false)
          }
          if (event === 'progress') {
            const m = data as { step?: string; message?: string; detail?: { percent?: number } }
            const pct = typeof m?.detail?.percent === 'number' ? m.detail.percent : null
            taskStorePatch(jobId, { stage: m?.step, percent: pct })
            taskHandle.update({ message: `文案成片${pct !== null ? ` · ${pct}%` : ''}`, percent: pct, stage: m?.message })
          }
        },
        onError(err) {
          toast.error(err.message)
          taskHandle.fail(err.message)
          taskStorePatch(jobId, { status: 'error', error: err.message })
          setComposing(false)
        },
      })
    } catch (e) {
      const msg = formatFastApiDetail(e) || (e as Error)?.message || '文案成片启动失败'
      toast.error(msg)
      taskHandle.fail(msg)
      if (jobId) taskStorePatch(jobId, { status: 'error', error: msg })
      setComposing(false)
    }
  }

  const handleExportJianyingDraft = async () => {
    const payload = buildComposePayload()
    if (!payload) return
    if (audioMode === 'tts_only' || audioMode === 'mix') {
      for (let i = 0; i < payload.length; i++) {
        if (!(payload[i].text || '').trim()) {
          toast.error(`导出剪映草稿（配音轨）时，第 ${i + 1} 段须填写配音文案（不可留空）。`)
          return
        }
      }
    }
    setJianyingExporting(true)
    try {
      const res = await scriptStockApi.exportJianyingDraft({
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
      if (res.mode === 'direct' && res.local_path) {
        toast.success(`剪映草稿已写入：${res.local_path}`)
        return
      }
      const a = document.createElement('a')
      a.href = res.url
      a.download = res.filename
      a.rel = 'noopener noreferrer'
      a.click()
      toast.success('剪映草稿已生成并开始下载')
      toastRecommendJianyingParentDir(toast)
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setJianyingExporting(false)
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
            （下方可选仅配音 / 仅原声 / 混合及分贝调节）。可与「合成配音成片」分开使用<strong className="text-slate-300"> 导出剪映草稿</strong>
            （仅 ZIP，不渲染 MP4；配音轨模式下每段须填文案）。本地与 <strong className="text-slate-300">Pexels / Pixabay / Unsplash</strong>{' '}
            均为卡片多选、角标为拼接顺序（与手动匹配一致）；<strong className="text-slate-300">Shift+点击</strong>
            可再叠同素材。图片仅存本地，成片时按配音时长做静帧；多图默认均分时长，不足时与视频一样循环/定格。请勿同段混用图片与视频。
          </p>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0 text-[11px]">
          <Link href="/settings#stock-media" className="text-sky-400 hover:underline">
            在线素材 API Key →
          </Link>
          <Link href="/settings" className="text-emerald-400/90 hover:underline">
            TTS 配音引擎 →
          </Link>
        </div>
      </div>

      <div className="rounded-xl border border-slate-700 bg-slate-950/40 p-4 space-y-3">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">AI 写文案（可选）</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <div className="sm:col-span-2 relative">
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="主题或关键词"
              className="w-full rounded-lg bg-slate-900 border border-slate-700 pl-3 pr-24 py-2 text-sm text-slate-200 outline-none focus:border-sky-500"
            />
            <div className="absolute right-1.5 top-1/2 -translate-y-1/2">
              <VoiceInputControl
                intent="文案素材成片 · AI 写文案的主题或关键词：把口述整理成简短主题词或检索用语。"
                value={topic}
                onTextChange={setTopic}
                merge="replace"
                disabled={generatingScript}
                className="relative"
              />
            </div>
          </div>
          <input
            type="number"
            min={1}
            max={20}
            value={numParas}
            onChange={(e) => setNumParas(Math.max(1, Math.min(20, Number(e.target.value) || 5)))}
            className="rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500"
          />
        </div>
        <div className="relative">
          <input
            value={styleHint}
            onChange={(e) => setStyleHint(e.target.value)}
            placeholder="风格补充（可选）：如 轻快短视频旁白、纪录片口吻…"
            className="w-full rounded-lg bg-slate-900 border border-slate-700 pl-3 pr-24 py-2 text-sm text-slate-200 outline-none focus:border-sky-500"
          />
          <div className="absolute right-1.5 top-1/2 -translate-y-1/2">
            <VoiceInputControl
              intent="文案素材成片 · AI 写文案的风格补充：把口述整理成一句风格/口吻/场景说明（如轻快短视频旁白、纪录片口吻），不要冗长解释。"
              value={styleHint}
              onTextChange={setStyleHint}
              merge="append"
              disabled={generatingScript}
              className="relative"
            />
          </div>
        </div>
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
        <div className="relative">
          <textarea
            value={fullScript}
            onChange={(e) => setFullScript(e.target.value)}
            rows={8}
            placeholder="粘贴完整文案，或先用上方 AI 生成…"
            className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 pr-14 pt-11 text-sm text-slate-200 outline-none focus:border-sky-500 resize-y min-h-[140px]"
          />
          <div className="absolute right-2 top-2 z-10">
            <VoiceInputControl
              intent="文案素材成片的「文案正文」：把口述整理成可分段配音/匹配画面的完整中文稿；保留标点与换行意图，不要输出操作说明。"
              value={fullScript}
              onTextChange={setFullScript}
              merge="append"
              disabled={splitting || generatingScript}
            />
          </div>
        </div>
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

          <StockOnlineCachePanel
            providers={['pexels', 'pixabay', 'unsplash']}
            itemsByProvider={{
              pexels: pexelsCacheItems,
              pixabay: pixabayCacheItems,
              unsplash: unsplashCacheItems,
            }}
            loadingByProvider={cacheLoading}
            clearingByProvider={cacheClearing}
            onRefresh={(p) => void loadOnlineCache(p)}
            onClear={(p) => void handleClearOnlineCache(p)}
            onDelete={(p, rel) => void handleDeleteOnlineCache(p, rel)}
            onPreview={(url) => setPexelsPreviewUrl(url)}
          />
          <p className="text-[10px] text-slate-500 leading-relaxed -mt-2">
            已缓存的在下方结果卡片可勾选；删除或清空后各段已勾选路径会自动取消。
          </p>

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

                <div className="flex flex-wrap rounded-lg border border-slate-700 overflow-hidden w-fit">
                  {(
                    [
                      { id: 'local' as const, label: '本地素材库', active: 'bg-violet-600 text-white' },
                      { id: 'pexels' as const, label: 'Pexels', active: 'bg-sky-600 text-white' },
                      { id: 'pixabay' as const, label: 'Pixabay', active: 'bg-emerald-600 text-white' },
                      { id: 'unsplash' as const, label: 'Unsplash', active: 'bg-amber-600 text-white' },
                    ] as const
                  ).map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() =>
                        setSegments((prev) =>
                          prev.map((s) => (s.id === seg.id ? { ...s, sourceTab: tab.id } : s)),
                        )
                      }
                      className={`px-3 py-1.5 text-xs font-medium ${
                        seg.sourceTab === tab.id ? tab.active : 'bg-slate-900 text-slate-400'
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
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
                ) : (() => {
                  const provider = seg.sourceTab as ScriptStockOnlineProvider
                  const selectedPaths = storedRelPathsForProvider(seg, provider)
                  const cacheItems =
                    provider === 'pexels'
                      ? pexelsCacheItems
                      : provider === 'pixabay'
                        ? pixabayCacheItems
                        : unsplashCacheItems
                  const dlBtnClass =
                    provider === 'pexels'
                      ? 'bg-sky-700 hover:bg-sky-600'
                      : provider === 'pixabay'
                        ? 'bg-emerald-700 hover:bg-emerald-600'
                        : 'bg-amber-700 hover:bg-amber-600'

                  type HitCard = {
                    key: string
                    mediaId: string | number
                    mediaType: 'image' | 'video'
                    image: string
                    title: string
                  }
                  const hits: HitCard[] =
                    provider === 'pexels'
                      ? [
                          ...seg.pexelsResults.map((pv) => ({
                            key: `v-${pv.id}`,
                            mediaId: pv.id,
                            mediaType: 'video' as const,
                            image: pv.image,
                            title: `${pv.duration}s · 视频`,
                          })),
                          ...seg.pexelsImageResults.map((pi) => ({
                            key: `i-${pi.id}`,
                            mediaId: pi.id,
                            mediaType: 'image' as const,
                            image: pi.image,
                            title: '图片',
                          })),
                        ]
                      : provider === 'pixabay'
                        ? [
                            ...seg.pixabayResults.map((pv) => ({
                              key: `v-${pv.id}`,
                              mediaId: pv.id,
                              mediaType: 'video' as const,
                              image: pv.image,
                              title: `${pv.duration}s · 视频`,
                            })),
                            ...seg.pixabayImageResults.map((pi) => ({
                              key: `i-${pi.id}`,
                              mediaId: pi.id,
                              mediaType: 'image' as const,
                              image: pi.image,
                              title: '图片',
                            })),
                          ]
                        : seg.unsplashResults.map((ph) => ({
                            key: ph.id,
                            mediaId: ph.id,
                            mediaType: 'image' as const,
                            image: ph.image,
                            title: ph.description?.slice(0, 24) || '图片',
                          }))

                  return (
                    <div className="space-y-3">
                      <div className="flex flex-wrap gap-2">
                        <input
                          value={seg.searchQuery}
                          onChange={(e) =>
                            setSegments((prev) =>
                              prev.map((s) =>
                                s.id === seg.id ? { ...s, searchQuery: e.target.value } : s,
                              ),
                            )
                          }
                          placeholder="英文搜索词，如 ocean sunset"
                          className="flex-1 min-w-[160px] rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200"
                        />
                        <button
                          type="button"
                          disabled={seg.searching}
                          onClick={() => void searchOnlineForSeg(seg.id, provider)}
                          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 border border-slate-600 hover:border-sky-500 text-sm"
                        >
                          {seg.searching ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Search className="w-4 h-4" />
                          )}
                          搜索 {onlineProviderLabel(provider)}
                        </button>
                      </div>
                      {selectedPaths.length > 0 ? (
                        <p className="text-[11px] text-emerald-400 flex flex-wrap items-center gap-1">
                          <Film className="w-3.5 h-3.5 shrink-0" />
                          本段已选 {selectedPaths.length} 个文件（顺序已标号）
                        </p>
                      ) : (
                        <p className="text-[11px] text-slate-500">
                          已缓存可勾选（<strong className="text-slate-400">Shift+点击</strong>
                          再叠同文件）；未缓存请先「下载」。
                        </p>
                      )}
                      <div className="flex gap-3 overflow-x-auto styled-scrollbar pb-2 -mx-1 px-1">
                        {hits.map((hit) => {
                          const cachedRel = bestCachedRelForId(
                            provider,
                            cacheItems,
                            hit.mediaId,
                            hit.mediaType,
                          )
                          const cached = Boolean(cachedRel)
                          const positions =
                            cachedRel != null && cached
                              ? orderPositionsForKey(selectedPaths, cachedRel)
                              : []
                          const isDl =
                            seg.downloadingKey === downloadKey(provider, hit.mediaType, hit.mediaId)
                          if (!cached) {
                            return (
                              <OrderedPickCard
                                key={hit.key}
                                imageUrl={hit.image}
                                title={hit.title}
                                subtitle="未下载"
                                orderPositions={[]}
                                selected={false}
                                disabled
                                onClick={() => {}}
                                footer={
                                  <div className="px-2 pb-2">
                                    <button
                                      type="button"
                                      disabled={isDl}
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        void downloadOnline(seg.id, provider, hit.mediaType, hit.mediaId)
                                      }}
                                      className={`w-full flex items-center justify-center gap-1 py-1.5 rounded text-[11px] text-white disabled:opacity-50 ${dlBtnClass}`}
                                    >
                                      {isDl ? (
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
                          const rel = cachedRel as string
                          return (
                            <OrderedPickCard
                              key={hit.key}
                              imageUrl={hit.image}
                              title={hit.title}
                              subtitle="已缓存 · 点缩略图勾选（Shift+再叠）"
                              orderPositions={positions}
                              selected={positions.length > 0}
                              previewVideoUrl={
                                hit.mediaType === 'video' ? storageBrowserVideoUrl(rel) : undefined
                              }
                              onClick={(e) => toggleOnlineRel(seg.id, provider, rel, e)}
                            />
                          )
                        })}
                      </div>
                    </div>
                  )
                })()}
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
                  在线素材多为环境声或无对白，混合时建议压低「原声」。
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

          <section className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-5 space-y-4">
            <div className="space-y-1">
              <p className="text-sm font-medium text-emerald-100/95">成片导出 · 背景音乐</p>
              <p className="text-[11px] text-slate-500 leading-relaxed">
                与口播快剪、手动匹配一致：在「合成配音成片」完成后叠加 BGM（FFmpeg 混音）。请先在
                <Link href="/settings" className="text-cyan-400 hover:text-cyan-300 underline underline-offset-2 mx-0.5">
                  设置 → BGM
                </Link>
                或
                <Link href="/bgm" className="text-cyan-400 hover:text-cyan-300 underline underline-offset-2 mx-0.5">
                  BGM 页
                </Link>
                上传曲目；开启混音后须选择一首，否则不会叠加。
              </p>
            </div>
            <AutoEditBgmMixPanel
              hideStrategy
              trackValueField="id"
              bgmTracks={bgmTracks}
              bgmListError={bgmListError}
              autoBgmMixEnabled={stockBgmEnabled}
              onAutoBgmMixEnabledChange={setStockBgmEnabled}
              autoBgmPlanPolicy="user"
              onAutoBgmPlanPolicyChange={() => {}}
              autoBgmTrackFilename={stockBgmTrackId}
              onAutoBgmTrackFilenameChange={setStockBgmTrackId}
              helperText="开关与曲目仅作用于「合成配音成片」；导出剪映草稿不含 BGM 混音。"
              emptyBgmHintPrefix="暂无曲目，请前往"
            />
          </section>

          <div className="rounded-xl border border-slate-700 bg-slate-950/40 p-4 flex flex-col gap-3">
            <div className="flex flex-col sm:flex-row gap-3 sm:items-end">
              <div className="flex-1 space-y-1">
                <label className="text-[10px] text-slate-500 uppercase tracking-wider">成片文件名前缀</label>
                <input
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200"
                />
              </div>
              <div className="flex flex-col sm:flex-row gap-2 shrink-0">
                <button
                  type="button"
                  disabled={composing || jianyingExporting}
                  onClick={() => void handleCompose()}
                  className="px-6 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 text-white text-sm font-semibold"
                >
                  {composing ? <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> : null}
                  合成配音成片
                </button>
                <button
                  type="button"
                  disabled={composing || jianyingExporting}
                  onClick={() => void handleExportJianyingDraft()}
                  className="px-6 py-3 rounded-xl border border-teal-500/60 bg-teal-500/15 hover:bg-teal-500/25 disabled:opacity-50 text-teal-100 text-sm font-semibold"
                >
                  {jianyingExporting ? <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> : null}
                  导出剪映草稿
                </button>
              </div>
            </div>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              混合模式下草稿仅含 TTS 解说轨（不含成片里的素材原声混合），可在剪映内再叠原声；解压后请按包内说明修补素材路径。
            </p>
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

      {pexelsPreviewUrl && typeof document !== 'undefined'
        ? createPortal(
            <div
              className="fixed inset-0 z-[3000] flex items-center justify-center bg-black/80 p-4"
              role="presentation"
              onClick={closePexelsPreview}
            >
              <div
                className="relative w-full max-w-3xl rounded-xl border border-slate-600 bg-black overflow-hidden shadow-2xl"
                role="dialog"
                aria-modal="true"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  onClick={closePexelsPreview}
                  className="absolute top-2 right-2 z-10 p-2 rounded-lg bg-slate-900/90 text-slate-200 hover:bg-slate-800 border border-slate-600"
                  aria-label="关闭预览"
                >
                  <X className="w-5 h-5" />
                </button>
                <video
                  ref={pexelsPreviewVideoRef}
                  src={pexelsPreviewUrl}
                  className="w-full max-h-[min(80vh,560px)] object-contain bg-black"
                  controls
                  playsInline
                  autoPlay
                />
              </div>
            </div>,
            document.body,
          )
        : null}

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
