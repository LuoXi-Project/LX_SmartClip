'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { Film, Search, Sparkles, Loader2, Filter, Play } from 'lucide-react'
import { searchApi, type SemanticSearchAssetResult, type SemanticSearchSegment, videosApi, type Video } from '@/lib/api'
import { videoStreamUrl, clipStreamUrl, fmt } from '@/app/match/_components/types'

type ViewMode = 'asset' | 'segment'
type PlayMode = 'video' | 'clip'

export default function AssetSearchPage() {
  const [query, setQuery] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>('asset')
  const [playMode, setPlayMode] = useState<PlayMode>('video')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [results, setResults] = useState<SemanticSearchAssetResult[]>([])
  const [selectedAssetId, setSelectedAssetId] = useState<string>('')
  const [selectedSegment, setSelectedSegment] = useState<SemanticSearchSegment | null>(null)
  const [highlightOnly, setHighlightOnly] = useState(false)
  const [videos, setVideos] = useState<Video[]>([])
  const [scopeVideoId, setScopeVideoId] = useState<string>('') // 单素材范围检索

  const videoRef = useRef<HTMLVideoElement | null>(null)

  const selectedAsset = useMemo(
    () => results.find((r) => r.asset_id === selectedAssetId) ?? results[0] ?? null,
    [results, selectedAssetId],
  )

  const selectedVideoMeta = useMemo(
    () => videos.find((v) => v.id === (scopeVideoId || selectedAsset?.asset_id || '')) ?? null,
    [videos, scopeVideoId, selectedAsset?.asset_id],
  )

  const durationSec = useMemo(() => {
    const d = selectedAsset?.duration
    if (typeof d === 'number' && Number.isFinite(d) && d > 0) return d
    const maxEnd = Math.max(
      0,
      ...(selectedAsset?.segments?.map((s) => Number(s.end_time) || 0) ?? [0]),
    )
    return maxEnd > 0 ? maxEnd : (selectedVideoMeta?.duration ?? 0) || 0
  }, [selectedAsset?.duration, selectedAsset?.segments, selectedVideoMeta?.duration])

  const playerSrc = useMemo(() => {
    if (selectedSegment && playMode === 'clip') {
      return clipStreamUrl(selectedSegment.clip_id)
    }
    if (selectedAsset) {
      return videoStreamUrl(selectedAsset.asset_id)
    }
    return ''
  }, [selectedAsset, selectedSegment, playMode])

  // 预取视频元信息（供筛选/展示）
  useEffect(() => {
    videosApi
      .list({ page: 1, page_size: 200, status: 'done' })
      .then((res) => setVideos(res.items || []))
      .catch(() => {})
  }, [])

  const runSearch = useCallback(
    async (q?: string) => {
      const text = (q ?? query).trim()
      if (!text) return
      setLoading(true)
      setError('')
      try {
        const res = await searchApi.semanticSearch({
          query: text,
          highlight_only: highlightOnly,
          filters: scopeVideoId ? { video_ids: [scopeVideoId] } : undefined,
        })
        setResults(res.results || [])
        if (res.results?.length) {
          const firstAsset = scopeVideoId
            ? res.results.find((r) => r.asset_id === scopeVideoId) ?? res.results[0]
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
    [query, highlightOnly, scopeVideoId],
  )

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

  const assetCount = results.length
  const segmentCount = results.reduce((sum, a) => sum + a.segments.length, 0)

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
              <span>语义检索</span>
            </div>
            <h1 className="text-xl font-semibold flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-indigo-400" />
              素材语义检索 & 高光浏览
            </h1>
            <p className="text-xs text-slate-500">
              输入一句话，跨素材检索相关片段；或在结果中优先浏览高光片段。
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
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="例如：人物近景微笑镜头 / 展示产品特写并有字幕的画面 / 显示操作步骤的片段"
                className="w-full pl-9 pr-28 py-2.5 bg-slate-900/60 border border-slate-700 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500/70"
              />
              <button
                type="submit"
                className="absolute right-1.5 top-1/2 -translate-y-1/2 px-3 py-1.5 rounded-lg bg-cyan-600 text-xs font-medium text-slate-900 hover:bg-cyan-500 transition-colors"
              >
                {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : '检索'}
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
            <div className="inline-flex items-center gap-2">
              <span className="text-slate-500">范围</span>
              <select
                value={scopeVideoId}
                onChange={(e) => setScopeVideoId(e.target.value)}
                className="px-2 py-1 rounded-lg bg-slate-900/60 border border-slate-700 text-[11px] text-slate-200 outline-none focus:border-indigo-500"
                title="限定在单素材内检索"
              >
                <option value="">全部素材</option>
                {videos
                  .filter((v) => v.status === 'done')
                  .map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
              </select>
              {scopeVideoId ? (
                <span className="text-[10px] text-slate-500">（单素材检索）</span>
              ) : null}
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
            >
              <Filter className="w-3 h-3" />
              <span>仅看高光片段</span>
            </button>

            {assetCount > 0 && (
              <span className="ml-auto">
                命中素材 {assetCount} 个 · 片段 {segmentCount} 条
              </span>
            )}
          </div>
        </form>

        {/* Main content */}
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1.2fr)] gap-4 min-h-[420px]">
          {/* Left: list */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden flex flex-col min-h-[260px]">
            {loading ? (
              <div className="flex-1 flex items-center justify-center text-sm text-slate-400 gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                正在检索素材…
              </div>
            ) : error ? (
              <div className="flex-1 flex items-center justify-center text-sm text-red-400 px-4 text-center">
                {error}
              </div>
            ) : !results.length ? (
              <div className="flex-1 flex flex-col items-center justify-center text-sm text-slate-500 gap-2 px-6 text-center">
                <Film className="w-10 h-10 text-slate-700" />
                <p>输入描述并点击「检索」，从已处理素材中查找匹配片段。</p>
              </div>
            ) : viewMode === 'asset' ? (
              <>
                <div className="px-4 py-2 border-b border-slate-800 text-xs text-slate-500 flex items-center justify-between">
                  <span>按素材分组 · 点击片段在右侧预览</span>
                </div>
                <div className="flex-1 overflow-auto divide-y divide-slate-800">
                  {results.map((asset) => (
                    <div
                      key={asset.asset_id}
                      className={`px-4 py-3 space-y-2 cursor-pointer transition-colors ${
                        selectedAsset?.asset_id === asset.asset_id ? 'bg-slate-900/80' : 'hover:bg-slate-900/60'
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
                      <div className="grid gap-1.5 mt-1">
                        {asset.segments.slice(0, 4).map((seg) => (
                          <button
                            key={seg.clip_id}
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              handlePickSegment(asset.asset_id, seg)
                            }}
                            className={`w-full text-left px-2 py-1.5 rounded-lg border text-[11px] transition-colors ${
                              selectedSegment?.clip_id === seg.clip_id
                                ? 'border-cyan-500/70 bg-cyan-500/10 text-slate-100'
                                : 'border-slate-800 bg-slate-900/40 text-slate-300 hover:border-slate-600'
                            }`}
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
                        ))}
                        {asset.segments.length > 4 && (
                          <span className="text-[10px] text-slate-500">
                            其余 {asset.segments.length - 4} 个片段可在右侧切换预览
                          </span>
                        )}
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
                <div className="flex-1 overflow-auto divide-y divide-slate-800">
                  {results.flatMap((asset) =>
                    asset.segments.map((seg) => ({ asset, seg })),
                  ).map(({ asset, seg }) => (
                    <button
                      key={seg.clip_id}
                      type="button"
                      onClick={() => {
                        handlePickSegment(asset.asset_id, seg)
                      }}
                      className={`w-full px-4 py-3 text-left text-[11px] transition-colors ${
                        selectedSegment?.clip_id === seg.clip_id
                          ? 'bg-slate-900/80'
                          : 'hover:bg-slate-900/60'
                      }`}
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
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Right: player & info */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 flex flex-col min-h-[260px]">
            <div className="px-4 py-2 border-b border-slate-800 text-xs text-slate-500 flex items-center justify-between">
              <span>预览 · 自动高光感知</span>
              {selectedAsset && (
                <span className="text-[11px] text-slate-400">
                  当前素材：{selectedAsset.asset_title || selectedAsset.asset_id}
                </span>
              )}
            </div>
            <div className="flex-1 flex flex-col">
              <div className="flex-1 min-h-[210px]">
                {playerSrc ? (
                  <video
                    key={playerSrc}
                    ref={playMode === 'video' ? videoRef : undefined}
                    src={playerSrc}
                    controls
                    autoPlay
                    className="w-full h-full object-contain bg-black rounded-b-xl"
                  />
                ) : (
                  <div className="h-full flex items-center justify-center text-sm text-slate-500">
                    请选择左侧的片段进行预览
                  </div>
                )}
              </div>

              {/* Timeline coloring (仅原片跳转模式) */}
              {playMode === 'video' && selectedAsset && durationSec > 0 && (
                <div className="border-t border-slate-800 px-4 py-3 space-y-2">
                  <div className="flex items-center justify-between text-[11px] text-slate-500">
                    <span>时间轴（命中片段/高光着色，可点击跳转）</span>
                    <span>总时长 {fmt(durationSec)}</span>
                  </div>
                  <div className="relative h-3 rounded-full bg-slate-800/70 overflow-hidden ring-1 ring-slate-700/60">
                    {/* match segments */}
                    {selectedAsset.segments.map((seg) => {
                      const left = Math.max(0, Math.min(1, (seg.start_time || 0) / durationSec))
                      const right = Math.max(0, Math.min(1, (seg.end_time || 0) / durationSec))
                      const w = Math.max(0.002, right - left)
                      const color = seg.is_highlight ? 'bg-amber-400/80' : 'bg-cyan-400/70'
                      return (
                        <button
                          key={seg.clip_id}
                          type="button"
                          title={`${fmt(seg.start_time)} ~ ${fmt(seg.end_time)} · ${seg.is_highlight ? '高光' : '命中'}`}
                          onClick={() => handlePickSegment(selectedAsset.asset_id, seg)}
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
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}

