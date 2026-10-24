'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { useAppStore } from '@/lib/store'
import { videosApi, formatFastApiDetail, type Video, type VideoListParams } from '@/lib/api'
import { Film, ListChecks, Trash2, RefreshCw } from 'lucide-react'
import { useConfirm } from '@/hooks/use-confirm'
import { useToast } from '@/components/ui/toast-provider'
import { useJobStream } from '@/hooks/use-job-stream'

import { UploadZone } from './_components/UploadZone'
import { KeywordIngestPanel } from './_components/KeywordIngestPanel'
import { VideoCard } from './_components/VideoCard'
import { SearchBar, type SortKey, type StatusFilter } from './_components/SearchBar'
import { Pagination } from './_components/Pagination'
import { PreviewModal } from './_components/PreviewModal'
import { ReencodeModal, type ReencodeOptions, type ReencodePreset } from './_components/ReencodeModal'

type DownloadPreset = 'quality' | 'balanced' | 'data_saver' | 'custom'

export default function LibraryPage() {
  const { addVideo, removeVideo } = useAppStore()
  const confirm = useConfirm()
  const toast = useToast()
  const { startJob } = useJobStream()

  // Server-driven list state
  const [items, setItems] = useState<Video[]>([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(true)
  /** 列表加载失败：与「空库」区分展示，避免误导用户以为素材丢失 */
  const [loadError, setLoadError] = useState('')

  // Upload / drag state
  const [uploading, setUploading] = useState(false)
  const [importingUrl, setImportingUrl] = useState(false)
  const [importUrl, setImportUrl] = useState('')
  const [importTitle, setImportTitle] = useState('')
  const [importPreset, setImportPreset] = useState<DownloadPreset>('balanced')
  const [importResolution, setImportResolution] = useState<'best' | '1080p' | '720p' | '480p' | '360p'>('best')
  const [importFpsLimit, setImportFpsLimit] = useState<'' | '24' | '30' | '60'>('')
  const [importPreferMp4, setImportPreferMp4] = useState(true)
  const [dragActive, setDragActive] = useState(false)

  // Preview state
  const [previewVideo, setPreviewVideo] = useState<Video | null>(null)
  const [previewError, setPreviewError] = useState(false)
  const [reencodeTarget, setReencodeTarget] = useState<Video | null>(null)
  const [reencodePreset, setReencodePreset] = useState<ReencodePreset>('preview_compatible')
  const [reencodeOptions, setReencodeOptions] = useState<ReencodeOptions>({
    vcodec: 'libx264',
    crf: 23,
    preset: 'veryfast',
    fps: '',
    maxHeight: '1080',
    audioBitrateK: 128,
  })

  // Search / filter / sort / pagination params
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('upload_at_desc')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)

  /** 多选批量删除 */
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const selectAllRef = useRef<HTMLInputElement>(null)

  // Debounce search query (300 ms)
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handleQueryChange = (v: string) => {
    setQuery(v)
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    debounceTimer.current = setTimeout(() => setDebouncedQuery(v), 300)
  }

  // Fetch from server
  const fetchVideos = useCallback(async (params: VideoListParams) => {
    setLoading(true)
    try {
      const res = await videosApi.list(params)
      setItems(res.items)
      setTotal(res.total)
      setTotalPages(res.total_pages)
      setLoadError('')
    } catch (err) {
      console.error('Failed to fetch videos:', err)
      setLoadError(formatFastApiDetail(err) || '素材列表加载失败，请检查后端服务是否已启动')
    } finally {
      setLoading(false)
    }
  }, [])

  const retryFetchVideos = useCallback(() => {
    fetchVideos({
      q: debouncedQuery || undefined,
      status: statusFilter !== 'all' ? statusFilter : undefined,
      sort,
      page,
      page_size: pageSize,
    })
  }, [fetchVideos, debouncedQuery, statusFilter, sort, page, pageSize])

  // Re-fetch whenever any param changes
  useEffect(() => {
    fetchVideos({
      q: debouncedQuery || undefined,
      status: statusFilter !== 'all' ? statusFilter : undefined,
      sort,
      page,
      page_size: pageSize,
    })
  }, [debouncedQuery, statusFilter, sort, page, pageSize, fetchVideos])

  // 删除后当前页可能超出总页数，回到最后一页
  useEffect(() => {
    if (loading) return
    if (items.length === 0 && total > 0 && page > totalPages) {
      setPage(Math.max(1, totalPages))
    }
  }, [loading, items.length, total, page, totalPages])

  // Reset to page 1 when filters/search/sort change
  useEffect(() => {
    setPage(1)
  }, [debouncedQuery, statusFilter, sort, pageSize])

  // 翻页或筛选变化时清空勾选，避免选中项已不在当前列表
  useEffect(() => {
    setSelectedIds(new Set())
  }, [page, debouncedQuery, statusFilter, sort, pageSize])

  const pageIds = items.map((v) => v.id)
  const selectedOnPage = pageIds.filter((id) => selectedIds.has(id)).length
  const allOnPageSelected = pageIds.length > 0 && selectedOnPage === pageIds.length
  const someOnPageSelected = selectedOnPage > 0 && !allOnPageSelected

  useEffect(() => {
    const el = selectAllRef.current
    if (!el) return
    el.indeterminate = someOnPageSelected
  }, [someOnPageSelected, allOnPageSelected, pageIds.length])

  // Upload handler
  const handleUpload = async (files: FileList) => {
    if (!files || files.length === 0) return
    setUploading(true)
    for (const file of Array.from(files)) {
      try {
        const response = await videosApi.upload(file)
        addVideo(response)
        toast.success(`上传成功: ${file.name}`)
      } catch (error) {
        console.error('Upload failed:', error)
        toast.error(`上传失败: ${file.name}`)
      }
    }
    setUploading(false)
    // Refresh current page after upload
    fetchVideos({
      q: debouncedQuery || undefined,
      status: statusFilter !== 'all' ? statusFilter : undefined,
      sort,
      page: 1,
      page_size: pageSize,
    })
    setPage(1)
  }

  const handleImportByUrl = async () => {
    const url = importUrl.trim()
    if (!url) {
      toast.error('请输入要下载的视频链接')
      return
    }
    setImportingUrl(true)
    try {
      const video = await videosApi.importByUrl({
        url,
        title: importTitle.trim() || undefined,
        resolution: importResolution,
        fps_limit: importFpsLimit ? Number(importFpsLimit) : undefined,
        prefer_mp4: importPreferMp4,
      })
      addVideo(video)
      toast.success('已开始下载并导入素材')
      setImportUrl('')
      setImportTitle('')
      await fetchVideos({
        q: debouncedQuery || undefined,
        status: statusFilter !== 'all' ? statusFilter : undefined,
        sort,
        page: 1,
        page_size: pageSize,
      })
      setPage(1)
    } catch (error) {
      console.error('Import by URL failed:', error)
      toast.error('链接导入失败，请检查链接格式或网络')
    } finally {
      setImportingUrl(false)
    }
  }

  const applyImportPreset = (preset: DownloadPreset) => {
    setImportPreset(preset)
    if (preset === 'quality') {
      setImportResolution('1080p')
      setImportFpsLimit('60')
      setImportPreferMp4(true)
      return
    }
    if (preset === 'balanced') {
      setImportResolution('720p')
      setImportFpsLimit('30')
      setImportPreferMp4(true)
      return
    }
    if (preset === 'data_saver') {
      setImportResolution('480p')
      setImportFpsLimit('30')
      setImportPreferMp4(true)
    }
  }

  // Rename handler
  const handleRename = async (id: string, name: string) => {
    try {
      await videosApi.rename(id, name)
      setItems((prev) => prev.map((v) => (v.id === id ? { ...v, name } : v)))
      if (previewVideo?.id === id) setPreviewVideo((p) => p ? { ...p, name } : p)
      toast.success('已重命名')
    } catch (error) {
      console.error('Rename failed:', error)
      toast.error('重命名失败，请重试')
      throw error
    }
  }

  // Delete handler
  const handleDelete = async (id: string) => {
    const ok = await confirm({
      title: '确认删除',
      description: '此操作将永久删除该视频及其所有处理数据，无法恢复。',
      confirmLabel: '删除',
      cancelLabel: '取消',
      variant: 'danger',
    })
    if (!ok) return
    try {
      await videosApi.delete(id)
      removeVideo(id)
      setSelectedIds((prev) => {
        if (!prev.has(id)) return prev
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      if (previewVideo?.id === id) closePreview()
      toast.success('视频已删除')
      // Refresh
      fetchVideos({
        q: debouncedQuery || undefined,
        status: statusFilter !== 'all' ? statusFilter : undefined,
        sort,
        page,
        page_size: pageSize,
      })
    } catch (error) {
      console.error('Delete failed:', error)
      toast.error('删除失败，请重试')
    }
  }

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

  const handleBatchDelete = async () => {
    const ids = [...selectedIds]
    if (ids.length === 0) return
    const ok = await confirm({
      title: '批量删除',
      description: `将永久删除已选的 ${ids.length} 个视频及其处理数据，无法恢复。`,
      confirmLabel: '删除',
      cancelLabel: '取消',
      variant: 'danger',
    })
    if (!ok) return
    const results = await Promise.allSettled(ids.map((id) => videosApi.delete(id)))
    let okCount = 0
    const failed: string[] = []
    results.forEach((r, i) => {
      if (r.status === 'fulfilled') {
        okCount += 1
        removeVideo(ids[i])
      } else {
        failed.push(ids[i])
      }
    })
    if (previewVideo && ids.includes(previewVideo.id)) closePreview()
    setSelectedIds(new Set(failed))
    if (failed.length === 0) exitSelectMode()
    await fetchVideos({
      q: debouncedQuery || undefined,
      status: statusFilter !== 'all' ? statusFilter : undefined,
      sort,
      page,
      page_size: pageSize,
    })
    if (okCount > 0 && failed.length === 0) {
      toast.success(`已删除 ${okCount} 个视频`)
    } else if (okCount > 0 && failed.length > 0) {
      toast.error(`已删除 ${okCount} 个，${failed.length} 个失败，可重试`)
    } else {
      toast.error('删除失败，请重试')
    }
  }

  const handleOpenReencode = (video: Video) => {
    setReencodeTarget(video)
    setReencodePreset('preview_compatible')
    setReencodeOptions({
      vcodec: 'libx264',
      crf: 23,
      preset: 'veryfast',
      fps: '',
      maxHeight: '1080',
      audioBitrateK: 128,
    })
  }

  const applyReencodePreset = (preset: ReencodePreset) => {
    setReencodePreset(preset)
    if (preset === 'preview_compatible') {
      setReencodeOptions({
        vcodec: 'libx264',
        crf: 22,
        preset: 'veryfast',
        fps: '30',
        maxHeight: '1080',
        audioBitrateK: 128,
      })
      return
    }
    if (preset === 'balanced') {
      setReencodeOptions({
        vcodec: 'libx264',
        crf: 23,
        preset: 'faster',
        fps: '30',
        maxHeight: '720',
        audioBitrateK: 128,
      })
      return
    }
    if (preset === 'small_size') {
      setReencodeOptions({
        vcodec: 'libx265',
        crf: 28,
        preset: 'fast',
        fps: '24',
        maxHeight: '720',
        audioBitrateK: 96,
      })
    }
  }

  const updateReencodeOptions = (next: ReencodeOptions) => {
    setReencodeOptions(next)
    setReencodePreset('custom')
  }

  const handleSubmitReencode = () => {
    if (!reencodeTarget) return
    const targetId = reencodeTarget.id
    startJob({
      create: () =>
        videosApi.reencode(targetId, {
          vcodec: reencodeOptions.vcodec,
          crf: reencodeOptions.crf,
          preset: reencodeOptions.preset,
          fps: reencodeOptions.fps ? Number(reencodeOptions.fps) : undefined,
          max_height: reencodeOptions.maxHeight ? Number(reencodeOptions.maxHeight) : undefined,
          acodec: 'aac',
          audio_bitrate_k: reencodeOptions.audioBitrateK,
        }),
      title: '重编码视频',
      kind: 'reencode',
      onDone: async () => {
        await fetchVideos({
          q: debouncedQuery || undefined,
          status: statusFilter !== 'all' ? statusFilter : undefined,
          sort,
          page,
          page_size: pageSize,
        })
      },
    })
    setReencodeTarget(null)
  }

  // Drag handlers
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true)
    else if (e.type === 'dragleave') setDragActive(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    handleUpload(e.dataTransfer.files)
  }

  // Preview handlers
  const openPreview = (video: Video) => {
    setPreviewError(false)
    setPreviewVideo(video)
  }

  const closePreview = () => {
    setPreviewVideo(null)
    setPreviewError(false)
  }

  const hasFilters = debouncedQuery || statusFilter !== 'all'

  return (
    <main className="min-h-screen bg-[#0d0f14]">
      {/* dot-grid background */}
      <div
        className="fixed inset-0 pointer-events-none"
        style={{
          backgroundImage:
            'radial-gradient(circle, rgba(148,163,184,0.06) 1px, transparent 1px)',
          backgroundSize: '28px 28px',
        }}
      />

      <div className="relative max-w-7xl mx-auto px-6 py-10">
        {/* ── Header ── */}
        <div className="mb-8">
          <div className="flex items-end justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-3xl font-bold tracking-tight text-slate-100">素材库</h1>
              <p className="text-slate-500 text-sm mt-1">管理和处理您的视频素材</p>
            </div>
            {!loading && total > 0 && (
              <span className="text-xs text-slate-600 tabular-nums">共 {total} 个视频</span>
            )}
          </div>
        </div>

        {/* ── Upload Zone ── */}
        <UploadZone
          uploading={uploading}
          importingUrl={importingUrl}
          importUrl={importUrl}
          importTitle={importTitle}
          importPreset={importPreset}
          importResolution={importResolution}
          importFpsLimit={importFpsLimit}
          importPreferMp4={importPreferMp4}
          dragActive={dragActive}
          onDrag={handleDrag}
          onDrop={handleDrop}
          onFileSelect={handleUpload}
          onImportUrlChange={setImportUrl}
          onImportTitleChange={setImportTitle}
          onImportPresetChange={applyImportPreset}
          onImportResolutionChange={(value) => {
            setImportResolution(value)
            setImportPreset('custom')
          }}
          onImportFpsLimitChange={(value) => {
            setImportFpsLimit(value)
            setImportPreset('custom')
          }}
          onImportPreferMp4Change={(value) => {
            setImportPreferMp4(value)
            setImportPreset('custom')
          }}
          onImportByUrl={handleImportByUrl}
        />

        {/* ── Keyword Ingest Panel（关键词采集） ── */}
        <KeywordIngestPanel
          onIngested={() => {
            fetchVideos({
              q: debouncedQuery || undefined,
              status: statusFilter !== 'all' ? statusFilter : undefined,
              sort,
              page: 1,
              page_size: pageSize,
            })
            setPage(1)
          }}
        />

        {/* ── Loading skeleton ── */}
        {loading ? (
          <div className="flex flex-col items-center justify-center py-24 gap-4">
            <div className="w-10 h-10 rounded-full border-2 border-slate-700 border-t-cyan-400 animate-spin" />
            <p className="text-slate-500 text-sm">加载中…</p>
          </div>
        ) : loadError ? (
          /* ── 加载失败：区别于空库，提供重试 ── */
          <div className="flex flex-col items-center justify-center py-24 gap-4">
            <div className="w-16 h-16 rounded-2xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center">
              <RefreshCw className="w-8 h-8 text-rose-400" />
            </div>
            <div className="text-center space-y-1">
              <p className="text-slate-200">素材列表加载失败</p>
              <p className="text-slate-500 text-sm break-all">{loadError}</p>
            </div>
            <button
              type="button"
              onClick={retryFetchVideos}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-medium transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              重试
            </button>
          </div>
        ) : total === 0 && !hasFilters ? (
          /* ── True empty state (no videos at all) ── */
          <div className="flex flex-col items-center justify-center py-24 gap-4">
            <div className="w-20 h-20 rounded-2xl bg-slate-800/60 flex items-center justify-center">
              <Film className="w-10 h-10 text-slate-600" />
            </div>
            <p className="text-slate-500">还没有上传任何视频，从上方开始上传吧</p>
          </div>
        ) : (
          <>
            {/* ── Search / Filter / Sort ── */}
            <SearchBar
              query={query}
              onQueryChange={handleQueryChange}
              sort={sort}
              onSortChange={setSort}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              total={total}
              filtered={total}
            />

            {/* ── 多选批量删除 ── */}
            {items.length > 0 && (
              <div className="flex flex-wrap items-center gap-3 mb-5 px-1">
                <button
                  type="button"
                  onClick={() => {
                    if (selectMode) exitSelectMode()
                    else setSelectMode(true)
                  }}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                    selectMode
                      ? 'bg-cyan-600/20 border-cyan-500/50 text-cyan-200'
                      : 'bg-slate-800/50 border-slate-600/60 text-slate-300 hover:border-slate-500'
                  }`}
                >
                  <ListChecks className="w-3.5 h-3.5" />
                  {selectMode ? '退出多选' : '多选'}
                </button>
                {selectMode && (
                  <>
                    <label className="inline-flex items-center gap-2 text-xs text-slate-400 cursor-pointer select-none">
                      <input
                        ref={selectAllRef}
                        type="checkbox"
                        checked={allOnPageSelected}
                        onChange={toggleSelectAllOnPage}
                        className="rounded border-slate-500 bg-slate-800 text-cyan-600 focus:ring-cyan-500/40"
                      />
                      全选本页
                    </label>
                    <span className="text-xs text-slate-500 tabular-nums">
                      已选 <span className="text-slate-300">{selectedIds.size}</span> 项
                    </span>
                    <button
                      type="button"
                      disabled={selectedIds.size === 0}
                      onClick={handleBatchDelete}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/35 hover:bg-red-500/25 disabled:opacity-40 disabled:pointer-events-none transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      批量删除
                    </button>
                  </>
                )}
              </div>
            )}

            {/* ── No results after filtering ── */}
            {items.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 gap-3">
                <Film className="w-12 h-12 text-slate-700" />
                <p className="text-slate-500 text-sm">没有符合条件的素材</p>
                <button
                  onClick={() => {
                    handleQueryChange('')
                    setStatusFilter('all')
                  }}
                  className="text-xs text-cyan-500 hover:text-cyan-400 transition-colors underline underline-offset-2"
                >
                  清除筛选条件
                </button>
              </div>
            ) : (
              <>
                {/* ── Grid ── */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
                  {items.map((video) => (
                    <VideoCard
                      key={video.id}
                      video={video}
                      onPreview={openPreview}
                      onDelete={handleDelete}
                      onRename={handleRename}
                      onReencode={handleOpenReencode}
                      multiSelectActive={selectMode}
                      selected={selectedIds.has(video.id)}
                      onToggleSelect={toggleSelectId}
                    />
                  ))}
                </div>

                {/* ── Pagination ── */}
                <Pagination
                  page={page}
                  totalPages={totalPages}
                  pageSize={pageSize}
                  onPageChange={setPage}
                  onPageSizeChange={setPageSize}
                />
              </>
            )}
          </>
        )}
      </div>

      {/* ── Preview Modal ── */}
      {previewVideo && (
        <PreviewModal
          video={previewVideo}
          hasError={previewError}
          onClose={closePreview}
          onError={() => setPreviewError(true)}
        />
      )}

      <ReencodeModal
        open={!!reencodeTarget}
        videoName={reencodeTarget?.name || ''}
        preset={reencodePreset}
        options={reencodeOptions}
        loading={false}
        onClose={() => setReencodeTarget(null)}
        onPresetChange={applyReencodePreset}
        onOptionsChange={updateReencodeOptions}
        onSubmit={handleSubmitReencode}
      />
    </main>
  )
}
