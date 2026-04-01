'use client'

import { X, AlertTriangle } from 'lucide-react'
import { useEffect } from 'react'
import type { Video } from '@/lib/store'

interface PreviewModalProps {
  video: Video
  hasError: boolean
  onClose: () => void
  onError: () => void
}

export function PreviewModal({ video, hasError, onClose, onError }: PreviewModalProps) {
  // Close on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-4xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal header */}
        <div className="flex items-center justify-between mb-3 px-1">
          <h3 className="text-slate-100 font-medium text-sm truncate max-w-[85%]" title={video.name}>
            {video.name}
          </h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700/80 transition-colors"
            title="关闭 (Esc)"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Player / Error */}
        <div className="rounded-xl overflow-hidden bg-black shadow-2xl ring-1 ring-slate-700/80 min-h-[200px] flex items-center justify-center">
          {hasError ? (
            <div className="flex flex-col items-center gap-3 px-8 py-12 text-center">
              <AlertTriangle className="w-10 h-10 text-amber-400/70" />
              <p className="text-slate-400 text-sm leading-relaxed">
                该视频格式浏览器不支持直接预览（如 MKV / AVI），<br />
                请使用本地播放器打开。
              </p>
            </div>
          ) : (
            <video
              key={video.id}
              src={`/api/videos/${video.id}/stream`}
              controls
              autoPlay
              className="w-full max-h-[75vh] object-contain"
              onError={onError}
            />
          )}
        </div>

        {/* hint */}
        <p className="text-center text-xs text-slate-600 mt-2">点击遮罩或按 Esc 关闭</p>
      </div>
    </div>
  )
}
