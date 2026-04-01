'use client'

import { useState, useRef, useEffect } from 'react'
import { Trash2, Play, Calendar, Film, Scissors, Pencil, Check, X } from 'lucide-react'
import type { Video } from '@/lib/store'

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  pending: { label: '待处理', cls: 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30' },
  processing: { label: '处理中', cls: 'bg-blue-500/15 text-blue-300 ring-1 ring-blue-500/30' },
  done: { label: '已完成', cls: 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30' },
  error: { label: '错误', cls: 'bg-red-500/15 text-red-300 ring-1 ring-red-500/30' },
}

interface VideoCardProps {
  video: Video
  onPreview: (video: Video) => void
  onDelete: (id: string) => void
  onRename: (id: string, name: string) => Promise<void>
}

export function VideoCard({ video, onPreview, onDelete, onRename }: VideoCardProps) {
  const status = STATUS_MAP[video.status] ?? STATUS_MAP.error
  const [thumbError, setThumbError] = useState(false)

  // Rename state
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(video.name)
  const [renaming, setRenaming] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Keep draft in sync if the video prop name changes externally
  useEffect(() => {
    if (!editing) setDraft(video.name)
  }, [video.name, editing])

  // Auto-focus & select all when entering edit mode
  useEffect(() => {
    if (editing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [editing])

  const thumbnailUrl = !thumbError
    ? `/api/videos/${video.id}/thumbnail`
    : null

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return null
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  const startEdit = (e: React.MouseEvent) => {
    e.stopPropagation()
    setDraft(video.name)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setDraft(video.name)
  }

  const commitEdit = async () => {
    const trimmed = draft.trim()
    if (!trimmed || trimmed === video.name) {
      cancelEdit()
      return
    }
    setRenaming(true)
    try {
      await onRename(video.id, trimmed)
      setEditing(false)
    } finally {
      setRenaming(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') commitEdit()
    else if (e.key === 'Escape') cancelEdit()
  }

  return (
    <div className="group flex flex-col bg-slate-800/40 backdrop-blur-sm border border-slate-700/60 rounded-xl overflow-hidden hover:border-cyan-500/40 hover:bg-slate-800/60 transition-all duration-200 hover:shadow-xl hover:shadow-cyan-900/10">
      {/* Thumbnail */}
      <div
        className="relative bg-slate-900/80 aspect-video flex items-center justify-center overflow-hidden cursor-pointer"
        onClick={() => onPreview(video)}
      >
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt={video.name}
            onError={() => setThumbError(true)}
            className="absolute inset-0 w-full h-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 bg-gradient-to-br from-slate-800/40 to-slate-900/80" />
        )}

        {/* Play button */}
        <div className="relative z-10 flex flex-col items-center gap-2">
          <div className="w-12 h-12 rounded-full bg-black/40 backdrop-blur-sm flex items-center justify-center group-hover:bg-cyan-600/80 transition-colors">
            <Play className="w-5 h-5 text-white/80 group-hover:text-white translate-x-0.5 transition-colors" />
          </div>
        </div>

        {/* Hover overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
        <span className="absolute bottom-2 right-2 text-xs text-white/70 bg-black/50 backdrop-blur-sm px-2 py-0.5 rounded-md opacity-0 group-hover:opacity-100 transition-opacity">
          点击预览
        </span>

        {/* Duration badge */}
        {video.duration && (
          <span className="absolute top-2 left-2 text-xs text-white/80 bg-black/50 backdrop-blur-sm px-2 py-0.5 rounded-md z-10">
            {formatDuration(video.duration)}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="flex flex-col flex-1 p-4 gap-3">
        {/* Title row */}
        <div className="flex items-start justify-between gap-2">
          {editing ? (
            /* ── Inline rename input ── */
            <div className="flex items-center gap-1 flex-1 min-w-0">
              <input
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={renaming}
                className="flex-1 min-w-0 bg-slate-700/80 border border-cyan-500/60 rounded-md px-2 py-0.5 text-sm text-slate-100 outline-none focus:ring-1 focus:ring-cyan-500/80 disabled:opacity-50"
              />
              <button
                onClick={commitEdit}
                disabled={renaming || !draft.trim()}
                className="shrink-0 p-1 rounded-md text-emerald-400 hover:bg-emerald-500/15 disabled:opacity-40 transition-colors"
                title="确认"
              >
                <Check className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={cancelEdit}
                disabled={renaming}
                className="shrink-0 p-1 rounded-md text-slate-400 hover:bg-slate-600/40 disabled:opacity-40 transition-colors"
                title="取消"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            /* ── Static title with edit button ── */
            <div className="flex items-start gap-1 flex-1 min-w-0">
              <h3
                className="font-medium text-slate-100 text-sm leading-snug line-clamp-2 flex-1"
                title={video.name}
              >
                {video.name}
              </h3>
              <button
                onClick={startEdit}
                className="shrink-0 p-1 rounded-md text-slate-500 hover:text-cyan-400 hover:bg-slate-700/60 opacity-0 group-hover:opacity-100 transition-all"
                title="重命名"
              >
                <Pencil className="w-3 h-3" />
              </button>
            </div>
          )}

          <span className={`shrink-0 px-2 py-0.5 text-xs rounded-full font-medium ${status.cls}`}>
            {status.label}
          </span>
        </div>

        {/* Meta */}
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span className="flex items-center gap-1">
            <Calendar className="w-3 h-3" />
            {new Date(video.upload_at).toLocaleDateString('zh-CN')}
          </span>
          {video.total_clips > 0 && (
            <span className="flex items-center gap-1">
              <Film className="w-3 h-3" />
              {video.total_clips} 片段
            </span>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-2 mt-auto pt-1">
          <a
            href={`/process?video=${video.id}`}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-cyan-600/90 text-white text-xs font-medium rounded-lg hover:bg-cyan-500 transition-colors"
          >
            <Scissors className="w-3.5 h-3.5" />
            去处理
          </a>
          <button
            onClick={() => onDelete(video.id)}
            className="px-3 py-2 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 hover:text-red-300 transition-colors"
            title="删除"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
