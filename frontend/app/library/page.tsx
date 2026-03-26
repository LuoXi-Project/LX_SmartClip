'use client'

import { useEffect, useState, useMemo } from 'react'
import { useAppStore } from '@/lib/store'
import { videosApi, type Video } from '@/lib/api'
import { Film } from 'lucide-react'

import { UploadZone } from './_components/UploadZone'
import { VideoCard } from './_components/VideoCard'
import { SearchBar, type SortKey, type StatusFilter } from './_components/SearchBar'
import { Pagination } from './_components/Pagination'
import { PreviewModal } from './_components/PreviewModal'

const PAGE_SIZE_DEFAULT = 12

function applyFilters(
  videos: Video[],
  query: string,
  status: StatusFilter,
  sort: SortKey,
): Video[] {
  let result = [...videos]

  if (query.trim()) {
    const q = query.trim().toLowerCase()
    result = result.filter((v) => v.name.toLowerCase().includes(q))
  }

  if (status !== 'all') {
    result = result.filter((v) => v.status === status)
  }

  result.sort((a, b) => {
    switch (sort) {
      case 'upload_at_asc':
        return new Date(a.upload_at).getTime() - new Date(b.upload_at).getTime()
      case 'name_asc':
        return a.name.localeCompare(b.name, 'zh-CN')
      case 'name_desc':
        return b.name.localeCompare(a.name, 'zh-CN')
      case 'upload_at_desc':
      default:
        return new Date(b.upload_at).getTime() - new Date(a.upload_at).getTime()
    }
  })

  return result
}

export default function LibraryPage() {
  const { videos, setVideos, addVideo, removeVideo } = useAppStore()

  // Remote data state
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [dragActive, setDragActive] = useState(false)

  // Preview state
  const [previewVideo, setPreviewVideo] = useState<Video | null>(null)
  const [previewError, setPreviewError] = useState(false)

  // Search / filter / sort state
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('upload_at_desc')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  // Pagination state
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_DEFAULT)

  // Load videos
  useEffect(() => {
    const fetchVideos = async () => {
      try {
        setLoading(true)
        const data = await videosApi.list()
        setVideos(data || [])
      } catch (error) {
        console.error('Failed to fetch videos:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchVideos()
  }, [setVideos])

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1)
  }, [query, statusFilter, sort, pageSize])

  // Filtered + sorted list
  const filtered = useMemo(
    () => applyFilters(videos, query, statusFilter, sort),
    [videos, query, statusFilter, sort],
  )

  // Paginated slice
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const paginated = useMemo(() => {
    const start = (page - 1) * pageSize
    return filtered.slice(start, start + pageSize)
  }, [filtered, page, pageSize])

  // Upload handler
  const handleUpload = async (files: FileList) => {
    if (!files || files.length === 0) return
    setUploading(true)
    for (const file of Array.from(files)) {
      try {
        const response = await videosApi.upload(file)
        addVideo(response)
      } catch (error) {
        console.error('Upload failed:', error)
        alert(`上传失败: ${file.name}`)
      }
    }
    setUploading(false)
  }

  // Delete handler
  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除这个视频吗？')) return
    try {
      await videosApi.delete(id)
      removeVideo(id)
      if (previewVideo?.id === id) closePreview()
    } catch (error) {
      console.error('Delete failed:', error)
      alert('删除失败')
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

  return (
    <main className="min-h-screen bg-[#0d0f14]">
      {/* subtle dot-grid background */}
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
            {!loading && videos.length > 0 && (
              <div className="text-xs text-slate-600 tabular-nums">
                共 {videos.length} 个视频
              </div>
            )}
          </div>
        </div>

        {/* ── Upload Zone ── */}
        <UploadZone
          uploading={uploading}
          dragActive={dragActive}
          onDrag={handleDrag}
          onDrop={handleDrop}
          onFileSelect={handleUpload}
        />

        {/* ── Loading ── */}
        {loading ? (
          <div className="flex flex-col items-center justify-center py-24 gap-4">
            <div className="w-10 h-10 rounded-full border-2 border-slate-700 border-t-cyan-400 animate-spin" />
            <p className="text-slate-500 text-sm">加载中…</p>
          </div>
        ) : videos.length === 0 ? (
          /* ── Empty state ── */
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
              onQueryChange={setQuery}
              sort={sort}
              onSortChange={setSort}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              total={videos.length}
              filtered={filtered.length}
            />

            {/* ── No results ── */}
            {filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 gap-3">
                <Film className="w-12 h-12 text-slate-700" />
                <p className="text-slate-500 text-sm">没有符合条件的素材</p>
                <button
                  onClick={() => {
                    setQuery('')
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
                  {paginated.map((video) => (
                    <VideoCard
                      key={video.id}
                      video={video}
                      onPreview={openPreview}
                      onDelete={handleDelete}
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
