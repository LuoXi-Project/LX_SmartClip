'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, CheckCircle2, Film, ListChecks, Loader2, Play, Search, Trash2, Video } from 'lucide-react'
import clsx from 'clsx'
import { rendersApi, formatFastApiDetail } from '@/lib/api'
import { Pagination } from '@/app/library/_components/Pagination'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useToast } from '@/components/ui/toast-provider'
import type { RenderItem, RenderSourceOption } from './types'
import { RenderPreviewModal } from './RenderPreviewModal'

interface RenderGridProps {
  /** 当前选中成片 id */
  selectedId: string | null
  onSelect: (item: RenderItem) => void
  /** 删除后回调（供父组件刷新发布表单的选中态） */
  onDeleted?: (id: string) => void
}

/** 格式化时长秒 → mm:ss。 */
function fmtDuration(sec: number): string {
  if (!sec || sec <= 0) return '--'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

/** 格式化文件大小。 */
function fmtSize(bytes: number): string {
  if (!bytes) return ''
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

export function RenderGrid({ selectedId, onSelect, onDeleted }: RenderGridProps) {
  const toast = useToast()
  const [items, setItems] = useState<RenderItem[]>([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)
  const [sources, setSources] = useState<RenderSourceOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [sourceFilter, setSourceFilter] = useState<string>('')
  const [previewItem, setPreviewItem] = useState<RenderItem | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)  // 删除等操作后强制刷新
  const [pendingDelete, setPendingDelete] = useState<RenderItem | null>(null)  // 待删除确认
  // 多选批量删除
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [pendingBatchDelete, setPendingBatchDelete] = useState(false)  // 批量删除确认
  const [batchDeleting, setBatchDeleting] = useState(false)
  const selectAllRef = useRef<HTMLInputElement>(null)
  const searchTimer = useRef<ReturnType<typeof setTimeout>>()

  // 加载来源选项
  useEffect(() => {
    rendersApi.sources().then((r) => setSources(r.sources)).catch(() => {})
  }, [])

  const loadPage = useCallback(async () => {
    setLoading(true)
    try {
      const r = await rendersApi.list({
        search: search.trim() || undefined,
        source: sourceFilter || undefined,
        page,
        page_size: pageSize,
      })
      setItems(r.items)
      setTotal(r.total)
      setTotalPages(r.total_pages)
      setError('')
    } catch (e) {
      setError(formatFastApiDetail(e))
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, search, sourceFilter, refreshKey])

  // 分页/每页条数/来源/强制刷新 变化 → 重新加载
  useEffect(() => {
    loadPage()
  }, [loadPage])

  // 搜索防抖（搜索时回到第一页）
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => {
      setPage(1)
    }, 350)
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current)
    }
  }, [search])

  // 来源变化时回到第一页
  useEffect(() => {
    setPage(1)
  }, [sourceFilter, pageSize])

  // 翻页/搜索/筛选变化时清空勾选，避免选中项已不在当前列表
  useEffect(() => {
    setSelectedIds(new Set())
  }, [page, search, sourceFilter, pageSize, refreshKey])

  // 当前页全选 / 半选状态（驱动「全选本页」复选框）
  const pageIds = items.map((it) => it.id)
  const selectedOnPage = pageIds.filter((id) => selectedIds.has(id)).length
  const allOnPageSelected = pageIds.length > 0 && selectedOnPage === pageIds.length
  const someOnPageSelected = selectedOnPage > 0 && !allOnPageSelected

  useEffect(() => {
    const el = selectAllRef.current
    if (!el) return
    el.indeterminate = someOnPageSelected
  }, [someOnPageSelected, allOnPageSelected, pageIds.length])

  const toggleSelectId = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAllOnPage = () => {
    setSelectedIds((prev) => {
      if (pageIds.length === 0) return prev
      const next = new Set(prev)
      if (pageIds.every((id) => next.has(id))) {
        for (const id of pageIds) next.delete(id)
      } else {
        for (const id of pageIds) next.add(id)
      }
      return next
    })
  }

  const exitSelectMode = () => {
    setSelectMode(false)
    setSelectedIds(new Set())
  }

  // 点删除按钮 → 打开确认弹窗（不立即删）
  const handleDeleteClick = (e: React.MouseEvent, item: RenderItem) => {
    e.stopPropagation()
    setPendingDelete(item)
  }

  // 确认删除 → 真正执行
  const handleDeleteConfirm = async () => {
    const target = pendingDelete
    setPendingDelete(null)
    if (!target) return
    try {
      await rendersApi.delete(target.id)
      // 删除成功后强制刷新；若当前页删空了，回退到上一页
      if (items.length <= 1 && page > 1) {
        setPage(page - 1)
      } else {
        setRefreshKey((k) => k + 1)
      }
      onDeleted?.(target.id)
      toast.success('已删除该成片')
    } catch (e2) {
      toast.error(`删除失败：${formatFastApiDetail(e2)}`)
    }
  }

  // 批量删除：并发删除已选项，按结果汇总；失败的保留勾选方便重试
  const handleBatchDeleteConfirm = async () => {
    setPendingBatchDelete(false)
    const ids = [...selectedIds]
    if (ids.length === 0) return
    setBatchDeleting(true)
    try {
      const results = await Promise.allSettled(ids.map((id) => rendersApi.delete(id)))
      const failed: string[] = []
      let okCount = 0
      results.forEach((r, i) => {
        if (r.status === 'fulfilled') {
          okCount += 1
          onDeleted?.(ids[i])
        } else {
          failed.push(ids[i])
        }
      })
      setSelectedIds(new Set(failed))
      if (failed.length === 0) exitSelectMode()
      if (failed.length === 0) {
        toast.success(`已删除 ${okCount} 个成片`)
      } else {
        toast.error(`删除完成：成功 ${okCount} 个、失败 ${failed.length} 个；失败项已保留勾选，可重试`)
      }
      // 删除后刷新当前页；若整页删空则回退
      if (okCount > 0 && items.length - okCount <= 0 && page > 1) {
        setPage(page - 1)
      } else {
        setRefreshKey((k) => k + 1)
      }
    } catch (e) {
      toast.error(`批量删除失败：${formatFastApiDetail(e)}`)
    } finally {
      setBatchDeleting(false)
    }
  }

  return (
    <section className="flex flex-col h-full">
      {/* 搜索 + 筛选 */}
      <div className="flex items-center gap-2 mb-3">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索成片名称…"
            className="w-full bg-slate-950/60 border border-slate-700 rounded pl-7 pr-2 py-1.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className="bg-slate-950/60 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
        >
          <option value="">全部来源</option>
          {sources.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      {/* 状态栏 + 多选工具条 */}
      <div className="flex flex-wrap items-center gap-2 mb-2 px-1">
        <div className="text-xs text-slate-500">
          {loading ? '加载中…' : `共 ${total} 个成片${search || sourceFilter ? `（已筛选）` : ''}`}
        </div>
        {!loading && items.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 ml-auto">
            <button
              type="button"
              onClick={() => {
                if (selectMode) exitSelectMode()
                else setSelectMode(true)
              }}
              className={clsx(
                'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors',
                selectMode
                  ? 'bg-indigo-600/20 border-indigo-500/50 text-indigo-200'
                  : 'bg-slate-800/50 border-slate-600/60 text-slate-300 hover:border-slate-500',
                batchDeleting && 'pointer-events-none opacity-60',
              )}
            >
              <ListChecks className="w-3.5 h-3.5" />
              {selectMode ? '退出多选' : '多选'}
            </button>
            {selectMode && (
              <>
                <label className="inline-flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer select-none">
                  <input
                    ref={selectAllRef}
                    type="checkbox"
                    checked={allOnPageSelected}
                    onChange={toggleSelectAllOnPage}
                    className="rounded border-slate-500 bg-slate-800 text-indigo-600 focus:ring-indigo-500/40"
                  />
                  全选本页
                </label>
                <span className="text-xs text-slate-500 tabular-nums">
                  已选 <span className="text-slate-300">{selectedIds.size}</span> 项
                </span>
                <button
                  type="button"
                  disabled={selectedIds.size === 0 || batchDeleting}
                  onClick={() => setPendingBatchDelete(true)}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/35 hover:bg-red-500/25 disabled:opacity-40 disabled:pointer-events-none transition-colors"
                >
                  {batchDeleting ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="w-3.5 h-3.5" />
                  )}
                  批量删除
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* 错误 */}
      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5 mb-2">
          {error}
        </div>
      )}

      {/* 网格 */}
      <div className="flex-1 overflow-y-auto styled-scrollbar pr-1">
        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />加载成片列表…
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-slate-500">
            <Film className="w-8 h-8 mb-2 opacity-40" />
            <p className="text-sm">暂无成片</p>
            <p className="text-xs mt-1">在智剪/影视解说等模块生成成片后会出现在这里</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2.5 pb-2">
            {items.map((it) => {
              const selected = it.id === selectedId
              const checked = selectedIds.has(it.id)
              return (
                <div
                  key={it.id}
                  className={clsx(
                    'group relative rounded-md border bg-slate-900/40 overflow-hidden transition-all',
                    selectMode && checked
                      ? 'border-indigo-500 ring-1 ring-indigo-500/50'
                      : selected
                        ? 'border-indigo-500 ring-1 ring-indigo-500/50'
                        : 'border-slate-800 hover:border-slate-600',
                  )}
                >
                  {/* 多选勾选框（仅多选模式显示） */}
                  {selectMode && (
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={checked}
                      onClick={(e) => {
                        e.stopPropagation()
                        toggleSelectId(it.id)
                      }}
                      className={clsx(
                        'absolute top-1 left-1 z-20 w-5 h-5 rounded border-2 flex items-center justify-center transition-colors',
                        checked
                          ? 'bg-indigo-600 border-indigo-400 text-white'
                          : 'bg-black/55 border-slate-400/80 text-transparent hover:border-indigo-400/70',
                      )}
                      title={checked ? '取消选择' : '选择'}
                    >
                      {checked && <Check className="w-3 h-3" />}
                    </button>
                  )}
                  {/* 缩略图（多选模式下点击切换勾选，否则点击预览） */}
                  <div
                    onClick={() => {
                      if (selectMode) toggleSelectId(it.id)
                      else setPreviewItem(it)
                    }}
                    className="aspect-video bg-slate-950 flex items-center justify-center relative cursor-pointer"
                  >
                    <Thumbnail id={it.id} hasCached={!!it.thumbnail_url} />
                    <span className="absolute bottom-1 right-1 text-[10px] px-1 py-0.5 rounded bg-black/70 text-slate-200">
                      {fmtDuration(it.duration)}
                    </span>
                    {/* 来源标签（多选模式下右移避开勾选框） */}
                    <span
                      className={clsx(
                        'absolute top-1 text-[10px] px-1.5 py-0.5 rounded bg-black/60 text-slate-300',
                        selectMode ? 'left-8' : 'left-1',
                      )}
                    >
                      {it.source_label}
                    </span>
                    {/* 操作按钮组（hover 显示，z-10 确保在中央播放按钮之上可点击；多选模式下隐藏） */}
                    {!selectMode && (
                      <div className="absolute top-1 right-1 z-10 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            setPreviewItem(it)
                          }}
                          className="p-1 rounded bg-black/60 text-slate-300 hover:text-white"
                          title="预览播放"
                        >
                          <Play className="w-3 h-3" />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => handleDeleteClick(e, it)}
                          className="p-1 rounded bg-black/60 text-slate-400 hover:text-red-300"
                          title="删除成片"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    )}
                    {/* 中央播放按钮（hover 显示，整个缩略图可点预览；多选模式下不显示） */}
                    {!selectMode && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          setPreviewItem(it)
                        }}
                        className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                        title="点击预览"
                      >
                        <span className="w-9 h-9 rounded-full bg-black/70 flex items-center justify-center">
                          <Play className="w-4 h-4 text-white ml-0.5" fill="currentColor" />
                        </span>
                      </button>
                    )}
                  </div>
                    {/* 文件名（多选模式下点击切换勾选，否则点击选中用于发布） */}
                  <div
                    onClick={() => {
                      if (selectMode) toggleSelectId(it.id)
                      else onSelect(it)
                    }}
                    className="p-2 cursor-pointer hover:bg-slate-800/40 transition-colors"
                  >
                    <div
                      className={clsx(
                        'text-xs truncate flex items-center gap-1',
                        selected ? 'text-indigo-200' : 'text-slate-300',
                      )}
                      title={it.filename}
                    >
                      {selected && <CheckCircle2 className="w-3 h-3 shrink-0 text-indigo-400" />}
                      {it.title || it.filename}
                    </div>
                    <div className="text-[10px] text-slate-500 mt-0.5 flex items-center gap-1.5">
                      <span>{new Date(it.created_at).toLocaleDateString()}</span>
                      {it.file_size > 0 && (
                        <>
                          <span>·</span>
                          <span>{fmtSize(it.file_size)}</span>
                        </>
                      )}
                    </div>
                    {/* 原素材标题（AI 文案生成时携带的上下文） */}
                    {it.material_title && (
                      <div
                        className="text-[10px] text-slate-500 mt-0.5 truncate"
                        title={`原素材：${it.material_title}`}
                      >
                        原素材：{it.material_title}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 分页（固定在列表底部，不随网格滚动；与素材库统一） */}
      {!loading && items.length > 0 && (
        <div className="pt-2 shrink-0 border-t border-slate-800/60 mt-1">
          <Pagination
            page={page}
            totalPages={totalPages}
            pageSize={pageSize}
            onPageChange={setPage}
            onPageSizeChange={setPageSize}
          />
        </div>
      )}

      {/* 预览 Modal */}
      {previewItem && (
        <RenderPreviewModal
          item={previewItem}
          videoSrc={rendersApi.videoUrl(previewItem.public_url)}
          isSelected={previewItem.id === selectedId}
          onClose={() => setPreviewItem(null)}
          onPublish={() => {
            onSelect(previewItem)
            setPreviewItem(null)
          }}
        />
      )}

      {/* 删除确认弹窗 */}
      <ConfirmDialog
        open={pendingDelete !== null}
        title="删除成片"
        description={`确定删除「${pendingDelete?.title || pendingDelete?.filename || ''}」？文件将被永久删除，无法恢复。`}
        confirmLabel="删除"
        cancelLabel="取消"
        variant="danger"
        onConfirm={handleDeleteConfirm}
        onCancel={() => setPendingDelete(null)}
      />

      {/* 批量删除确认弹窗 */}
      <ConfirmDialog
        open={pendingBatchDelete}
        title="批量删除"
        description={`将永久删除已选的 ${selectedIds.size} 个成片文件，无法恢复。`}
        confirmLabel="删除"
        cancelLabel="取消"
        variant="danger"
        onConfirm={handleBatchDeleteConfirm}
        onCancel={() => setPendingBatchDelete(false)}
      />
    </section>
  )
}

/** 缩略图组件：优先用缓存 URL，否则用懒生成 API（首次访问触发后端生成）。 */
function Thumbnail({ id, hasCached }: { id: string; hasCached: boolean }) {
  // 缓存的 URL 走 /storage（快）；未缓存走 /api/renders/{id}/thumbnail（懒生成，首次慢）
  const url = hasCached ? null : rendersApi.thumbnailUrl(id)
  const [errored, setErrored] = useState(false)

  if (errored) {
    return <Video className="w-8 h-8 text-slate-700" />
  }
  if (url) {
    return (
      <img
        src={url}
        alt="缩略图"
        loading="lazy"
        onError={() => setErrored(true)}
        className="w-full h-full object-cover"
      />
    )
  }
  // 有缓存但前端拿不到 URL（thumbnail_url 已在 DB 但 list 未返回具体 url）→ 也走 API
  return (
    <img
      src={rendersApi.thumbnailUrl(id)}
      alt="缩略图"
      loading="lazy"
      onError={() => setErrored(true)}
      className="w-full h-full object-cover"
    />
  )
}
