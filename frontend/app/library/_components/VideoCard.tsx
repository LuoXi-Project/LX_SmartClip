'use client'

import { Trash2, Play, Calendar, Film, Scissors } from 'lucide-react'
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
}

export function VideoCard({ video, onPreview, onDelete }: VideoCardProps) {
  const status = STATUS_MAP[video.status] ?? STATUS_MAP.error

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return null
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div className="group flex flex-col bg-slate-800/40 backdrop-blur-sm border border-slate-700/60 rounded-xl overflow-hidden hover:border-cyan-500/40 hover:bg-slate-800/60 transition-all duration-200 hover:shadow-xl hover:shadow-cyan-900/10">
      {/* Thumbnail */}
      <div
        className="relative bg-slate-900/80 aspect-video flex items-center justify-center overflow-hidden cursor-pointer"
        onClick={() => onPreview(video)}
      >
        {/* subtle noise texture */}
        <div className="absolute inset-0 bg-gradient-to-br from-slate-800/40 to-slate-900/80" />
        <div className="relative z-10 flex flex-col items-center gap-2">
          <div className="w-12 h-12 rounded-full bg-slate-700/80 flex items-center justify-center group-hover:bg-cyan-600/80 transition-colors">
            <Play className="w-5 h-5 text-slate-300 group-hover:text-white translate-x-0.5 transition-colors" />
          </div>
        </div>
        {/* hover overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
        <span className="absolute bottom-2 right-2 text-xs text-white/70 bg-black/50 backdrop-blur-sm px-2 py-0.5 rounded-md opacity-0 group-hover:opacity-100 transition-opacity">
          点击预览
        </span>
        {/* duration badge */}
        {video.duration && (
          <span className="absolute top-2 left-2 text-xs text-white/80 bg-black/50 backdrop-blur-sm px-2 py-0.5 rounded-md">
            {formatDuration(video.duration)}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="flex flex-col flex-1 p-4 gap-3">
        {/* Title + Status */}
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-medium text-slate-100 text-sm leading-snug line-clamp-2 flex-1" title={video.name}>
            {video.name}
          </h3>
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
