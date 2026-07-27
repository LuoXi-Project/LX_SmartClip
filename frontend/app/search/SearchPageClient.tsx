'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { Film, Search, Sparkles, Loader2, Filter, Play, ChevronDown, X, Download, SlidersHorizontal } from 'lucide-react'
import {
  searchApi,
  clipDownloadUrl,
  type SemanticSearchAssetResult,
  type SemanticSearchSegment,
  type MatchMode,
  videosApi,
  type Video,
  type HighlightBrowseAssetResult,
} from '@/lib/api'
import { videoStreamUrl, clipStreamUrl, fmt } from '@/app/match/_components/types'
import { VoiceInputControl } from '@/components/ui/voice-input'

type ViewMode = 'asset' | 'segment'
type PlayMode = 'video' | 'clip'
type DataMode = 'semantic' | 'highlight'

export default function AssetSearchPage() {
  const [query, setQuery] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>('asset')
  const [playMode, setPlayMode] = useState<PlayMode>('video')
  const [dataMode, setDataMode] = useState<DataMode>('semantic')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [results, setResults] = useState<SemanticSearchAssetResult[]>([])
  const [highlightResults, setHighlightResults] = useState<HighlightBrowseAssetResult[]>([])
  const [selectedAssetId, setSelectedAssetId] = useState<string>('')
  const [selectedSegment, setSelectedSegment] = useState<SemanticSearchSegment | null>(null)
  const [highlightOnly, setHighlightOnly] = useState(false)
  const [videos, setVideos] = useState<Video[]>([])
  const [scopeVideoIds, setScopeVideoIds] = useState<string[]>([]) // 多选范围
  const [scopeOpen, setScopeOpen] = useState(false)
  const [playerDurationSec, setPlayerDurationSec] = useState(0)
  // 检索参数（仅语义检索模式生效）
  const [topK, setTopK] = useState<number>(20)
  const [topN, setTopN] = useState<number>(10)
  const [matchMode, setMatchMode] = useState<MatchMode | ''>('')
  const [refine, setRefine] = useState<boolean>(true)
  const [advOpen, setAdvOpen] = useState(false)
  const [downloadingClipId, setDownloadingClipId] = useState<string | null>(null)

  const videoRef = useRef<HTMLVideoElement | null>(null)

  const selectedAsset = useMemo(
    () => results.find((r) => r.asset_id === selectedAssetId) ?? results[0] ?? null,
    [results, selectedAssetId],
  )

  const displayAssets = useMemo<SemanticSearchAssetResult[]>(() => {
    if (dataMode === 'semantic') return results
    return (highlightResults || []).map((a) => ({
      asset_id: a.asset_id,
      asset_title: a.asset_title,
      duration: a.duration ?? null,
      cover_url: a.cover_url ?? null,
      // 在高光浏览模式下，asset_score=最高高光分
      asset_score: a.asset_score,
      segments: (a.segments || []).map((s) => ({
        clip_id: s.clip_id,
        start_time: s.start_time,
        end_time: s.end_time,
        duration: s.duration,
        // 复用 score 字段用于排序展示
        score: s.highlight_score,
        summary_text: s.summary_text ?? null,
        is_highlight: true,
        highlight_score: s.highlight_score,
        thumbnail_url: null,
        preview_url: null,
      })),
    }))
  }, [dataMode, results, highlightResults])

  const effectiveAsset = useMemo(
    () => displayAssets.find((r) => r.asset_id === selectedAssetId) ?? displayAssets[0] ?? null,
    [displayAssets, selectedAssetId],
  )

  const selectedVideoMeta = useMemo(
    () =>
      videos.find((v) => v.id === (scopeVideoIds[0] || selectedAsset?.asset_id || '')) ?? null,
    [videos, scopeVideoIds, selectedAsset?.asset_id],
  )

  const durationSec = useMemo(() => {
    const d = effectiveAsset?.duration
    if (typeof d === 'number' && Number.isFinite(d) && d > 0) return d
    const maxEnd = Math.max(
      0,
      ...(effectiveAsset?.segments?.map((s) => Number(s.end_time) || 0) ?? [0]),
    )
    return maxEnd > 0 ? maxEnd : (selectedVideoMeta?.duration ?? 0) || 0
  }, [effectiveAsset?.duration, effectiveAsset?.segments, selectedVideoMeta?.duration])

  const timelineDurationSec = useMemo(
    () => (playerDurationSec > 0 ? playerDurationSec : durationSec),
    [playerDurationSec, durationSec],
  )

  const playerSrc = useMemo(() => {
    if (selectedSegment && playMode === 'clip') {
      return clipStreamUrl(selectedSegment.clip_id)
    }
    if (effectiveAsset) {
      return videoStreamUrl(effectiveAsset.asset_id)
    }
    return ''
  }, [effectiveAsset, selectedSegment, playMode])

  // 预取视频元信息（供筛选/展示）
  useEffect(() => {
    videosApi
      .list({ page: 1, page_size: 200, status: 'done' })
      .then((res) => setVideos(res.items || []))
      .catch(() => {})
  }, [])

  const scopeLabel = useMemo(() => {
    if (!scopeVideoIds.length) return '全部素材'
    if (scopeVideoIds.length === 1) {
      const v = videos.find((x) => x.id === scopeVideoIds[0])
      return v?.name || scopeVideoIds[0]
    }
    return `已选 ${scopeVideoIds.length} 个素材`
  }, [scopeVideoIds, videos])

  const runSearch = useCallback(
    async (q?: string) => {
      const text = (q ?? query).trim()
      if (!text) return
      setLoading(true)
      setError('')
      try {
        const res = await searchApi.semanticSearch({
          query: text,
          top_k: topK,
          top_n: topN,
          highlight_only: highlightOnly,
          match_mode: matchMode || undefined,
          refine,
          filters: scopeVideoIds.length ? { video_ids: scopeVideoIds } : undefined,
        })
        setResults(res.results || [])
        setHighlightResults([])
        if (res.results?.length) {
          const firstAsset =
            scopeVideoIds.length === 1
              ? res.results.find((r) => r.asset_id === scopeVideoIds[0]) ?? res.results[0]
              : res.results[0]
          setSelectedAssetId(firstAsset.asset_id)
          setSelectedSegment(firstAsset.segments[0] ?? null)
        } else {
          setSelectedAssetId('')
          setSelectedSegment(null)
        }
      } catch (e: unknown) {
        setError(
          (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
            '检索失败，请稍后重试',
        )
      } finally {
        setLoading(false)
      }
    },
    [query, highlightOnly, scopeVideoIds, topK, topN, matchMode, refine],
  )

  const loadHighlights = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await searchApi.browseHighlights({
        limit_assets: scopeVideoIds.length ? scopeVideoIds.length : 20,
        limit_segments_per_asset: 10,
        min_score: 0.3,
        filters: scopeVideoIds.length ? { video_ids: scopeVideoIds } : undefined,
      })
      setHighlightResults(res.results || [])
      setResults([])
      const first = (res.results || [])[0]
      if (first) {
        setSelectedAssetId(first.asset_id)
        const seg0 = first.segments?.[0]
        setSelectedSegment(
          seg0
            ? {
                clip_id: seg0.clip_id,
                start_time: seg0.start_time,
                end_time: seg0.end_time,
                duration: seg0.duration,
                score: seg0.highlight_score,
                summary_text: seg0.summary_text,
                is_highlight: true,
                highlight_score: seg0.highlight_score,
              }
            : null,
        )
      } else {
        setSelectedAssetId('')
        setSelectedSegment(null)
      }
    } catch (e: unknown) {
      setError(
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          '加载高光失败，请稍后重试',
      )
    } finally {
      setLoading(false)
    }
  }, [scopeVideoIds])

  useEffect(() => {
    if (dataMode !== 'highlight') return
    void loadHighlights()
  }, [dataMode, loadHighlights])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    void runSearch()
  }

  const seekVideoTo = (t: number) => {
    const el = videoRef.current
    if (!el) return
    try {
      el.currentTime = Math.max(0, t || 0)
      void el.play().catch(() => {})
    } catch {
      // ignore
    }
  }

  const handlePickSegment = (assetId: string, seg: SemanticSearchSegment) => {
    setSelectedAssetId(assetId)
    setSelectedSegment(seg)
    if (playMode === 'video') {
      // 等待 video src 更新后再 seek
      setTimeout(() => seekVideoTo(seg.start_time), 0)
    }
  }

  const handleDownloadClip = async (clipId: string) => {
    if (!clipId || downloadingClipId) return
    setDownloadingClipId(clipId)
    try {
      const url = clipDownloadUrl(clipId)
      const resp = await fetch(url)
      if (!resp.ok) {
        const txt = await resp.text().catch(() => '')
        throw new Error(txt || `下载失败（${resp.status}）`)
      }
      // 从 content-disposition 拿文件名；否则用 clipId 兜底
      const cd = resp.headers.get('content-disposition') || ''
      const m = /filename\*?=(?:UTF-8'')?["']?([^"';]+)/i.exec(cd)
      const filename = m?.[1] ? decodeURIComponent(m[1]) : `${clipId.slice(0, 8)}.mp4`
      const blob = await resp.blob()
      const objUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(objUrl), 1000)
    } catch (e) {
      setError(`片段下载失败：${(e as Error).message || e}`)
    } finally {
      setDownloadingClipId(null)
    }
  }

  useEffect(() => {
    // 切换素材/播放源后，等待新 video metadata 覆盖时长
    setPlayerDurationSec(0)
  }, [playerSrc, playMode])

  const assetCount = dataMode === 'highlight' ? highlightResults.length : results.length
  const segmentCount =
    dataMode === 'highlight'
      ? highlightResults.reduce((sum, a) => sum + a.segments.length, 0)
      : results.reduce((sum, a) => sum + a.segments.length, 0)

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-100">
      <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        {/* Header */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Link href="/library" className="hover:text-slate-200">
                素材库
              </Link>
              <span>›</span>
              <span>素材检索</span>
            </div>
            <h1 className="text-xl font-semibold flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-indigo-400" />
              素材检索
            </h1>
            <p className="text-xs text-slate-500">
              输入一句话做语义检索，或切换到高光浏览；命中片段可在右侧预览。
            </p>
          </div>
          <div className="hidden sm:flex items-center gap-2 text-[11px] text-slate-500">
            <Film className="w-4 h-4 text-slate-400" />
            <span>已处理素材：{videos.filter((v) => v.status === 'done').length}</span>
          </div>
        </div>

        {/* Search bar */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-slate-800 bg-slate-900/40 px-4 py-3 flex flex-col gap-3"
        >
          <div className="flex flex-col gap-2 md:flex-row md:items-center">
            <div className="relative flex-1 min-w-0">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none z-0" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="例如：人物近景微笑镜头 / 展示产品特写并有字幕的画面 / 显示操作步骤的片段"
                className="w-full pl-9 pr-[7.5rem] py-2.5 bg-slate-900/60 border border-slate-700 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500/70"
              />
              <div className="absolute right-1.5 top-1/2 -translate-y-1/2 z-10 flex items-center gap-1">
                <VoiceInputControl
                  intent="这是素材语义检索/高光浏览的查询框：请把用户口述整理成一句适合向量检索与 LLM 精排的中文检索描述，保留镜头/主体/动作/情绪等关键信息，不要输出无关说明。"
                  value={query}
                  onTextChange={setQuery}
                  merge="replace"
                />
                <button
                  type="submit"
                  className="px-3 py-1.5 rounded-lg bg-cyan-600 text-xs font-medium text-slate-900 hover:bg-cyan-500 transition-colors"
                >
                  {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : '检索'}
                </button>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
            {/* Data mode */}
            <div className="inline-flex items-center gap-1 rounded-full bg-slate-900/80 border border-slate-700 px-1 py-1">
              <button
                type="button"
                onClick={() => setDataMode('semantic')}
                className={`px-2.5 py-0.5 rounded-full ${
                  dataMode === 'semantic'
                    ? 'bg-indigo-500 text-slate-900'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
                title="语义检索：会走向量召回 + LLM 精排"
              >
                语义检索
              </button>
              <button
                type="button"
                onClick={() => setDataMode('highlight')}
                className={`px-2.5 py-0.5 rounded-full ${
                  dataMode === 'highlight'
                    ? 'bg-amber-400 text-slate-900'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
                title="高光浏览：直接读取分析结果，不走向量/LLM"
              >
                高光浏览
              </button>
            </div>

            {/* Scope multi-select */}
            <div className="relative inline-flex items-center gap-2">
              <span className="text-slate-500">范围</span>
              <button
                type="button"
                onClick={() => setScopeOpen((v) => !v)}
                className="inline-flex items-center gap-2 px-2 py-1 rounded-lg bg-slate-900/60 border border-slate-700 text-[11px] text-slate-200 hover:border-slate-500 transition-colors"
                title="支持多选/全选"
              >
                <span className="max-w-[220px] truncate">{scopeLabel}</span>
                <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
              </button>
              {scopeVideoIds.length > 0 && (
                <button
                  type="button"
                  onClick={() => setScopeVideoIds([])}
                  className="p-1 rounded-md border border-slate-800 bg-slate-900/40 hover:border-slate-600"
                  title="清空范围"
                >
                  <X className="w-3.5 h-3.5 text-slate-400" />
                </button>
              )}

              {scopeOpen && (
                <div className="absolute z-20 top-7 left-10 w-[380px] max-w-[80vw] rounded-xl border border-slate-700 bg-slate-950/95 backdrop-blur p-2 shadow-2xl">
                  <div className="flex items-center justify-between px-2 py-1">
                    <span className="text-[10px] text-slate-500">多选素材范围（done）</span>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          const all = videos.filter((v) => v.status === 'done').map((v) => v.id)
                          setScopeVideoIds(all)
                        }}
                        className="text-[10px] text-cyan-300 hover:text-cyan-200"
                      >
                        全选
                      </button>
                      <button
                        type="button"
                        onClick={() => setScopeVideoIds([])}
                        className="text-[10px] text-slate-400 hover:text-slate-200"
                      >
                        清空
                      </button>
                    </div>
                  </div>
                  <div className="max-h-56 overflow-auto styled-scrollbar divide-y divide-slate-800">
                    {videos
                      .filter((v) => v.status === 'done')
                      .map((v) => {
                        const checked = scopeVideoIds.includes(v.id)
                        return (
                          <label
                            key={v.id}
                            className="flex items-center gap-2 px-2 py-2 text-[11px] text-slate-200 hover:bg-slate-900/50 cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => {
                                setScopeVideoIds((prev) =>
                                  prev.includes(v.id) ? prev.filter((x) => x !== v.id) : [...prev, v.id],
                                )
                              }}
                            />
                            <span className="truncate">{v.name}</span>
                          </label>
                        )
                      })}
                  </div>
                  <div className="px-2 py-1 text-[10px] text-slate-500">
                    当前选择：{scopeVideoIds.length ? `${scopeVideoIds.length} 个` : '全部素材'}
                  </div>
                </div>
              )}
            </div>

            <div className="inline-flex items-center gap-1 rounded-full bg-slate-900/80 border border-slate-700 px-1 py-1">
              <button
                type="button"
                onClick={() => setViewMode('asset')}
                className={`px-2.5 py-0.5 rounded-full ${
                  viewMode === 'asset'
                    ? 'bg-indigo-500 text-slate-900'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                按素材分组
              </button>
              <button
                type="button"
                onClick={() => setViewMode('segment')}
                className={`px-2.5 py-0.5 rounded-full ${
                  viewMode === 'segment'
                    ? 'bg-emerald-400 text-slate-900'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                扁平片段视图
              </button>
            </div>

            <div className="inline-flex items-center gap-1 rounded-full bg-slate-900/80 border border-slate-700 px-1 py-1">
              <button
                type="button"
                onClick={() => setPlayMode('video')}
                className={`px-2.5 py-0.5 rounded-full ${
                  playMode === 'video'
                    ? 'bg-slate-200 text-slate-900'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
                title="在原片中跳转到时间点（支持时间轴着色）"
              >
                原片跳转
              </button>
              <button
                type="button"
                onClick={() => setPlayMode('clip')}
                className={`px-2.5 py-0.5 rounded-full ${
                  playMode === 'clip'
                    ? 'bg-slate-200 text-slate-900'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
                title="直接播放命中片段切片"
              >
                片段播放
              </button>
            </div>

            <button
              type="button"
              onClick={() => setHighlightOnly((v) => !v)}
              className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 ${
                highlightOnly
                  ? 'border-amber-400/70 bg-amber-500/10 text-amber-200'
                  : 'border-slate-700 bg-slate-900/60 text-slate-400 hover:border-slate-500 hover:text-slate-200'
              }`}
              disabled={dataMode === 'highlight'}
              title={dataMode === 'highlight' ? '高光浏览模式下默认都是高光' : '只看高光片段（语义检索结果）'}
            >
              <Filter className="w-3 h-3" />
              <span>仅看高光片段</span>
            </button>

            {/* 高级检索参数（仅语义检索生效） */}
            <div className="relative inline-flex items-center">
              <button
                type="button"
                onClick={() => setAdvOpen((v) => !v)}
                disabled={dataMode === 'highlight'}
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 transition-colors ${
                  advOpen || matchMode || refine === false
                    ? 'border-cyan-500/70 bg-cyan-500/10 text-cyan-200'
                    : 'border-slate-700 bg-slate-900/60 text-slate-400 hover:border-slate-500 hover:text-slate-200'
                } ${dataMode === 'highlight' ? 'opacity-50 cursor-not-allowed' : ''}`}
                title={
                  dataMode === 'highlight'
                    ? '高光浏览模式不走向量/LLM，无需检索参数'
                    : '自定义检索数量 / 模式 / 精排'
                }
              >
                <SlidersHorizontal className="w-3 h-3" />
                <span>检索参数</span>
                {(matchMode || refine === false) && (
                  <span className="ml-0.5 px-1 rounded-full bg-cyan-500/30 text-[9px] text-cyan-100">
                    已自定义
                  </span>
                )}
              </button>

              {advOpen && dataMode === 'semantic' && (
                <div className="absolute z-20 top-7 right-0 w-[300px] max-w-[88vw] rounded-xl border border-slate-700 bg-slate-950/95 backdrop-blur p-3 shadow-2xl space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-slate-300 font-medium">检索参数（本次语义检索）</span>
                    <button
                      type="button"
                      onClick={() => setAdvOpen(false)}
                      className="p-1 rounded-md hover:bg-slate-800 text-slate-400"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <label className="flex flex-col gap-1">
                      <span className="text-[10px] text-slate-500">向量初筛 top_k</span>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={topK}
                        onChange={(e) => {
                          const v = Number(e.target.value)
                          if (Number.isFinite(v)) setTopK(Math.max(1, Math.min(100, Math.round(v))))
                        }}
                        className="px-2 py-1 bg-slate-900/70 border border-slate-700 rounded-md text-[11px] text-slate-100 focus:outline-none focus:border-cyan-500/70"
                      />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="text-[10px] text-slate-500">返回片段 top_n</span>
                      <input
                        type="number"
                        min={1}
                        max={50}
                        value={topN}
                        onChange={(e) => {
                          const v = Number(e.target.value)
                          if (Number.isFinite(v)) setTopN(Math.max(1, Math.min(50, Math.round(v))))
                        }}
                        className="px-2 py-1 bg-slate-900/70 border border-slate-700 rounded-md text-[11px] text-slate-100 focus:outline-none focus:border-cyan-500/70"
                      />
                    </label>
                  </div>

                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] text-slate-500">检索模式（覆盖全局）</span>
                    <select
                      value={matchMode}
                      onChange={(e) => setMatchMode(e.target.value as MatchMode | '')}
                      className="px-2 py-1 bg-slate-900/70 border border-slate-700 rounded-md text-[11px] text-slate-100 focus:outline-none focus:border-cyan-500/70"
                    >
                      <option value="">自动（沿用设置页）</option>
                      <option value="vector">向量（Embedding+FAISS）</option>
                      <option value="text">文本（ASR/VLM 文本相似）</option>
                      <option value="llm_only">纯 LLM（跨层语义对齐）</option>
                    </select>
                  </label>

                  <label className="flex items-center justify-between gap-2 px-1">
                    <div className="flex flex-col">
                      <span className="text-[11px] text-slate-200">LLM 精排</span>
                      <span className="text-[10px] text-slate-500">
                        {refine ? '启用：LLM 二次重排，更准但更慢' : '关闭：仅用初筛排序，更快'}
                      </span>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={refine}
                      onClick={() => setRefine((v) => !v)}
                      className={`relative w-9 h-5 rounded-full transition-colors ${
                        refine ? 'bg-cyan-500' : 'bg-slate-700'
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                          refine ? 'translate-x-4' : 'translate-x-0'
                        }`}
                      />
                    </button>
                  </label>

                  <div className="flex items-center justify-between pt-1 border-t border-slate-800">
                    <button
                      type="button"
                      onClick={() => {
                        setTopK(20)
                        setTopN(10)
                        setMatchMode('')
                        setRefine(true)
                      }}
                      className="text-[10px] text-slate-400 hover:text-slate-200"
                    >
                      重置默认
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setAdvOpen(false)
                        void runSearch()
                      }}
                      className="px-2.5 py-1 rounded-md bg-cyan-600 text-[11px] text-slate-900 font-medium hover:bg-cyan-500"
                    >
                      应用并检索
                    </button>
                  </div>
                </div>
              )}
            </div>

            {assetCount > 0 && (
              <span className="ml-auto">
                命中素材 {assetCount} 个 · 片段 {segmentCount} 条
              </span>
            )}
          </div>
        </form>

        {/* —— 语义检索与高光（独立） —— */}
        <section aria-labelledby="search-workspace-heading" className="space-y-3">
          <h2 id="search-workspace-heading" className="text-sm font-medium text-slate-300 px-0.5">
            语义检索与高光浏览
          </h2>
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1.2fr)] gap-4 min-h-[420px] lg:items-stretch">
          {/* Left: list */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden flex flex-col min-h-0 h-full">
            {loading ? (
              <div className="flex-1 flex items-center justify-center text-sm text-slate-400 gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                正在检索素材…
              </div>
            ) : error ? (
              <div className="flex-1 flex items-center justify-center text-sm text-red-400 px-4 text-center">
                {error}
              </div>
            ) : !displayAssets.length ? (
              <div className="flex-1 flex flex-col items-center justify-center text-sm text-slate-500 gap-2 px-6 text-center">
                <Film className="w-10 h-10 text-slate-700" />
                {dataMode === 'highlight' ? (
                  <p>正在浏览高光：无需检索即可从已分析结果中展示高光片段。</p>
                ) : (
                  <p>输入描述并点击「检索」，从已处理素材中查找匹配片段。</p>
                )}
              </div>
            ) : viewMode === 'asset' ? (
              <>
                <div className="px-4 py-2 border-b border-slate-800 text-xs text-slate-500 flex items-center justify-between">
                  <span>按素材分组 · 点击片段在右侧预览</span>
                </div>
                <div className="flex-1 overflow-auto styled-scrollbar divide-y divide-slate-800">
                  {displayAssets.map((asset) => (
                    <div
                      key={asset.asset_id}
                      className={`px-4 py-3 space-y-2 cursor-pointer transition-colors ${
                        effectiveAsset?.asset_id === asset.asset_id ? 'bg-slate-900/80' : 'hover:bg-slate-900/60'
                      }`}
                      onClick={() => {
                        setSelectedAssetId(asset.asset_id)
                        setSelectedSegment(asset.segments[0] ?? null)
                        if (playMode === 'video' && asset.segments[0]) {
                          setTimeout(() => seekVideoTo(asset.segments[0].start_time), 0)
                        }
                      }}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-6 rounded bg-slate-800 flex items-center justify-center text-[10px] text-slate-400">
                          {Math.round(asset.duration ?? 0)}s
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-slate-100 truncate">
                            {asset.asset_title || asset.asset_id}
                          </div>
                          <div className="text-[11px] text-slate-500">
                            片段 {asset.segments.length} · 最高相关度{' '}
                            <span className="text-cyan-300">{asset.asset_score.toFixed(3)}</span>
                          </div>
                        </div>
                      </div>
                      <div className="grid gap-1.5 mt-1 max-h-72 overflow-y-auto styled-scrollbar pr-1">
                        {asset.segments.map((seg) => (
                          <div
                            key={seg.clip_id}
                            className={`group relative w-full text-left px-2 py-1.5 pr-7 rounded-lg border text-[11px] transition-colors ${
                              selectedSegment?.clip_id === seg.clip_id
                                ? 'border-cyan-500/70 bg-cyan-500/10 text-slate-100'
                                : 'border-slate-800 bg-slate-900/40 text-slate-300 hover:border-slate-600'
                            }`}
                          >
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                handlePickSegment(asset.asset_id, seg)
                              }}
                              className="w-full text-left"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-slate-400">
                                  {fmt(seg.start_time)} ~ {fmt(seg.end_time)}
                                </span>
                                <span className="text-[10px] text-amber-300">
                                  {seg.is_highlight ? '高光' : '普通'} ·{' '}
                                  {seg.highlight_score.toFixed(2)}
                                </span>
                              </div>
                              {seg.summary_text && (
                                <p className="mt-0.5 line-clamp-2 text-[11px] text-slate-200">
                                  {seg.summary_text}
                                </p>
                              )}
                            </button>
                            <button
                              type="button"
                              title="下载该片段原文件"
                              onClick={(e) => {
                                e.stopPropagation()
                                void handleDownloadClip(seg.clip_id)
                              }}
                              disabled={downloadingClipId === seg.clip_id}
                              className="absolute top-1 right-1 p-1 rounded-md text-slate-500 opacity-0 group-hover:opacity-100 hover:bg-slate-800 hover:text-cyan-300 transition-opacity disabled:opacity-60"
                            >
                              {downloadingClipId === seg.clip_id ? (
                                <Loader2 className="w-3 h-3 animate-spin" />
                              ) : (
                                <Download className="w-3 h-3" />
                              )}
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <>
                <div className="px-4 py-2 border-b border-slate-800 text-xs text-slate-500 flex items-center justify-between">
                  <span>片段列表（按相关度降序）</span>
                </div>
                <div className="flex-1 overflow-auto styled-scrollbar divide-y divide-slate-800">
                  {displayAssets.flatMap((asset) =>
                    asset.segments.map((seg) => ({ asset, seg })),
                  ).map(({ asset, seg }) => (
                    <div
                      key={seg.clip_id}
                      className={`group relative w-full px-4 py-3 pr-10 text-left text-[11px] transition-colors ${
                        selectedSegment?.clip_id === seg.clip_id
                          ? 'bg-slate-900/80'
                          : 'hover:bg-slate-900/60'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => {
                          handlePickSegment(asset.asset_id, seg)
                        }}
                        className="w-full text-left"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <div className="text-slate-300 truncate">
                              {asset.asset_title || asset.asset_id}
                            </div>
                            <div className="text-slate-500">
                              {fmt(seg.start_time)} ~ {fmt(seg.end_time)}
                            </div>
                          </div>
                          <div className="text-right shrink-0">
                            <div className="text-cyan-300">
                              相似度 {seg.score.toFixed(3)}
                            </div>
                            <div className="text-amber-300">
                              {seg.is_highlight ? '高光' : '普通'} ·{' '}
                              {seg.highlight_score.toFixed(2)}
                            </div>
                          </div>
                        </div>
                        {seg.summary_text && (
                          <p className="mt-1 text-slate-200 line-clamp-2">
                            {seg.summary_text}
                          </p>
                        )}
                      </button>
                      <button
                        type="button"
                        title="下载该片段原文件"
                        onClick={(e) => {
                          e.stopPropagation()
                          void handleDownloadClip(seg.clip_id)
                        }}
                        disabled={downloadingClipId === seg.clip_id}
                        className="absolute top-1/2 -translate-y-1/2 right-2 p-1.5 rounded-md text-slate-500 opacity-0 group-hover:opacity-100 hover:bg-slate-800 hover:text-cyan-300 transition-opacity disabled:opacity-60"
                      >
                        {downloadingClipId === seg.clip_id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Download className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Right: player & info — 外层撑满行高以便 sticky 在整页滚动时有效；内层卡片吸顶 */}
          <div className="min-h-0 h-full flex flex-col">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 flex flex-col min-h-[260px] w-full sticky top-12 z-10 self-start max-h-[calc(100dvh-3rem)] overflow-y-auto styled-scrollbar overscroll-contain">
              <div className="px-4 py-2 border-b border-slate-800 text-xs text-slate-500 flex items-center justify-between">
                <span>检索预览</span>
                {effectiveAsset && (
                  <span className="text-[11px] text-slate-400 truncate max-w-[55%] text-right">
                    {effectiveAsset.asset_title || effectiveAsset.asset_id}
                  </span>
                )}
              </div>
            <div className="flex flex-col">
              <div className="min-h-[210px] max-h-[min(50vh,420px)] aspect-video w-full">
                {playerSrc ? (
                  <video
                    key={playerSrc}
                    ref={playMode === 'video' ? videoRef : undefined}
                    src={playerSrc}
                    onLoadedMetadata={(e) => {
                      const next = e.currentTarget.duration
                      setPlayerDurationSec(Number.isFinite(next) && next > 0 ? next : 0)
                    }}
                    controls
                    autoPlay
                    className="w-full h-full object-contain bg-black rounded-b-xl"
                  />
                ) : (
                  <div className="h-full flex items-center justify-center text-sm text-slate-500">
                    在左侧选择片段以预览检索命中
                  </div>
                )}
              </div>

              {/* Timeline coloring (仅原片跳转模式) */}
              {playMode === 'video' && effectiveAsset && timelineDurationSec > 0 && (
                <div className="border-t border-slate-800 px-4 py-3 space-y-2">
                  <div className="flex items-center justify-between text-[11px] text-slate-500">
                    <span>时间轴（命中片段/高光着色，可点击跳转）</span>
                    <span>总时长 {fmt(timelineDurationSec)}</span>
                  </div>
                  <div className="relative h-3 rounded-full bg-slate-800/70 overflow-hidden ring-1 ring-slate-700/60">
                    {/* match segments */}
                    {effectiveAsset.segments.map((seg) => {
                      const left = Math.max(0, Math.min(1, (seg.start_time || 0) / timelineDurationSec))
                      const right = Math.max(0, Math.min(1, (seg.end_time || 0) / timelineDurationSec))
                      const w = Math.max(0.002, right - left)
                      const color = seg.is_highlight ? 'bg-amber-400/80' : 'bg-cyan-400/70'
                      return (
                        <button
                          key={seg.clip_id}
                          type="button"
                          title={`${fmt(seg.start_time)} ~ ${fmt(seg.end_time)} · ${seg.is_highlight ? '高光' : '命中'}`}
                          onClick={() => handlePickSegment(effectiveAsset.asset_id, seg)}
                          className={`absolute top-0 h-full ${color} hover:brightness-110 transition-all`}
                          style={{
                            left: `${left * 100}%`,
                            width: `${w * 100}%`,
                          }}
                        />
                      )
                    })}
                  </div>
                  {selectedSegment && (
                    <div className="flex items-center gap-2 text-[11px] text-slate-400">
                      <Play className="w-3.5 h-3.5 text-emerald-300" />
                      <span>
                        当前：{fmt(selectedSegment.start_time)} ~ {fmt(selectedSegment.end_time)}
                      </span>
                      <span className="text-slate-600">
                        · {selectedSegment.is_highlight ? '高光' : '命中'}
                      </span>
                    </div>
                  )}
                </div>
              )}

              {selectedSegment && (
                <div className="border-t border-slate-800 px-4 py-3 space-y-1.5 text-[11px] text-slate-300">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400">
                      时间：{fmt(selectedSegment.start_time)} ~ {fmt(selectedSegment.end_time)}
                    </span>
                    <span className="text-slate-500">
                      · 时长 {fmt(selectedSegment.duration)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-slate-400">
                    <span>
                      相似度 <span className="text-cyan-300">{selectedSegment.score.toFixed(3)}</span>
                    </span>
                    <span>
                      高光分数{' '}
                      <span className="text-amber-300">
                        {selectedSegment.highlight_score.toFixed(2)}{' '}
                        {selectedSegment.is_highlight ? '(高光)' : ''}
                      </span>
                    </span>
                  </div>
                  {selectedSegment.summary_text && (
                    <p className="text-[11px] leading-relaxed text-slate-200">
                      {selectedSegment.summary_text}
                    </p>
                  )}
                  <div className="pt-1.5">
                    <button
                      type="button"
                      onClick={() => void handleDownloadClip(selectedSegment.clip_id)}
                      disabled={downloadingClipId === selectedSegment.clip_id}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-600/90 hover:bg-cyan-500 text-[11px] font-medium text-slate-900 transition-colors disabled:opacity-60"
                    >
                      {downloadingClipId === selectedSegment.clip_id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Download className="w-3.5 h-3.5" />
                      )}
                      <span>{downloadingClipId === selectedSegment.clip_id ? '下载中…' : '下载片段'}</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
            </div>
          </div>
        </div>
        </section>

      </div>
    </main>
  )
}

