'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { useAppStore } from '@/lib/store'
import { videosApi, type Video, type VideoListParams } from '@/lib/api'
import { Film } from 'lucide-react'
import { useConfirm } from '@/hooks/use-confirm'
import { useToast } from '@/components/ui/toast-provider'

import { UploadZone } from './_components/UploadZone'
import { VideoCard } from './_components/VideoCard'
import { SearchBar, type SortKey, type StatusFilter } from './_components/SearchBar'
import { Pagination } from './_components/Pagination'
import { PreviewModal } from './_components/PreviewModal'

type DownloadPreset = 'quality' | 'balanced' | 'data_saver' | 'custom'

export default function LibraryPage() {
  const { addVideo, removeVideo } = useAppStore()
  const confirm = useConfirm()
  const toast = useToast()

  // Server-driven list state
  const [items, setItems] = useState<Video[]>([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(true)

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

  // Search / filter / sort / pagination params
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('upload_at_desc')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)

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
    } catch (err) {
      console.error('Failed to fetch videos:', err)
    } finally {
      setLoading(false)
    }
  }, [])

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

  // Reset to page 1 when filters/search/sort change
  useEffect(() => {
    setPage(1)
  }, [debouncedQuery, statusFilter, sort, pageSize])

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
      toast.error('链接导入失败，请检查链接或 yt-dlp 环境')
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

        {/* ── Loading skeleton ── */}
        {loading ? (
          <div className="flex flex-col items-center justify-center py-24 gap-4">
            <div className="w-10 h-10 rounded-full border-2 border-slate-700 border-t-cyan-400 animate-spin" />
            <p className="text-slate-500 text-sm">加载中…</p>
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
    </main>
  )
}
