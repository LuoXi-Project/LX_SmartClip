'use client'

import { useCallback, useEffect, useRef, useState, type MouseEvent } from 'react'
import { AlertCircle, ChevronLeft, ChevronRight, Loader2, Search } from 'lucide-react'
import type { Video } from '@/lib/api'
import { API_BASE_URL, formatFastApiDetail, videosApi } from '@/lib/api'
import { orderPositionsForKey } from '@/lib/match/orderedSelection'
import { OrderedPickCard } from './OrderedPickCard'

const LIBRARY_PAGE_SIZE = 24

/**
 * 文案素材成片 · 单段「本地素材库」：独立搜索、分页、勾选（与本段绑定）
 */
export function SegmentLocalLibraryBlock({
  localVideoIds,
  onToggleVideo,
  onListItems,
}: {
  localVideoIds: string[]
  onToggleVideo: (videoId: string, e: MouseEvent) => void
  /** 把当前页条目并入全局素材元数据（自选区间 / 合成） */
  onListItems: (items: Video[]) => void
}) {
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const debRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [page, setPage] = useState(1)
  const [items, setItems] = useState<Video[]>([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    return () => {
      if (debRef.current) clearTimeout(debRef.current)
    }
  }, [])

  const handleQueryChange = useCallback((v: string) => {
    setQuery(v)
    if (debRef.current) clearTimeout(debRef.current)
    debRef.current = setTimeout(() => setDebouncedQuery(v), 300)
  }, [])

  useEffect(() => {
    setPage(1)
  }, [debouncedQuery])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    void (async () => {
      try {
        const res = await videosApi.list({
          q: debouncedQuery.trim() || undefined,
          page,
          page_size: LIBRARY_PAGE_SIZE,
          sort: 'upload_at_desc',
          exclude_status: 'error',
        })
        if (cancelled) return
        setItems(res.items)
        setTotal(res.total)
        setTotalPages(res.total_pages)
        onListItems(res.items)
      } catch (e) {
        if (!cancelled) setLoadError(formatFastApiDetail(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [debouncedQuery, page, onListItems])

  return (
    <div className="rounded-xl border border-violet-500/25 bg-slate-900/40 p-3 space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
          <input
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="搜索素材名称…"
            className="w-full rounded-lg bg-slate-950 border border-slate-700 pl-9 pr-3 py-2 text-sm text-slate-200 outline-none focus:border-violet-500"
          />
        </div>
      </div>

      {loadError ? <p className="text-xs text-rose-400">{loadError}</p> : null}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-slate-500 tabular-nums">
          {loading ? (
            <span className="inline-flex items-center gap-1.5">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              加载中…
            </span>
          ) : (
            <>共 {total} 条 · 第 {page} / {totalPages} 页</>
          )}
        </p>
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="p-1.5 rounded-lg border border-slate-600 text-slate-300 disabled:opacity-30 hover:bg-slate-800 transition-colors"
            aria-label="上一页"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            type="button"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            className="p-1.5 rounded-lg border border-slate-600 text-slate-300 disabled:opacity-30 hover:bg-slate-800 transition-colors"
            aria-label="下一页"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="relative min-h-[88px]">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-slate-500 text-sm">
            <Loader2 className="w-5 h-5 animate-spin mr-2 shrink-0" />
            加载素材列表…
          </div>
        ) : items.length === 0 ? (
          <div className="flex items-center gap-2 text-xs text-amber-300 py-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {debouncedQuery.trim()
              ? '无匹配素材，请换个关键词或清空搜索。'
              : '暂无可用素材。请先上传或在素材处理中完成解析。'}
          </div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-2 -mx-0.5 px-0.5">
            {items.map((v) => {
              const positions = orderPositionsForKey(localVideoIds, v.id)
              const thumb = `${API_BASE_URL}/api/videos/${v.id}/thumbnail`
              return (
                <OrderedPickCard
                  key={v.id}
                  imageUrl={thumb}
                  title={v.name}
                  subtitle={v.status === 'done' ? '已处理' : v.status}
                  orderPositions={positions}
                  selected={positions.length > 0}
                  onClick={(e) => onToggleVideo(v.id, e)}
                />
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
