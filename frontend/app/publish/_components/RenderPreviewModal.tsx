'use client'

import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Send, X } from 'lucide-react'
import type { RenderItem } from './types'

interface RenderPreviewModalProps {
  item: RenderItem
  videoSrc: string
  onClose: () => void
  /** 是否已选中用于发布（控制按钮文案） */
  isSelected: boolean
  onPublish: () => void
}

export function RenderPreviewModal({
  item,
  videoSrc,
  onClose,
  isSelected,
  onPublish,
}: RenderPreviewModalProps) {
  const [hasError, setHasError] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)

  // Esc 关闭
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
        className="relative w-full max-w-3xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between mb-3 px-1 gap-2">
          <h3
            className="text-slate-100 font-medium text-sm truncate flex-1"
            title={item.filename}
          >
            {item.title || item.filename}
          </h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700/80 transition-colors shrink-0"
            title="关闭 (Esc)"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 播放器 / 错误 */}
        <div className="rounded-xl overflow-hidden bg-black shadow-2xl ring-1 ring-slate-700/80 min-h-[200px] flex items-center justify-center">
          {hasError ? (
            <div className="flex flex-col items-center gap-3 px-8 py-12 text-center">
              <AlertTriangle className="w-10 h-10 text-amber-400/70" />
              <p className="text-slate-400 text-sm leading-relaxed">
                该视频格式浏览器不支持直接预览，<br />
                请使用本地播放器打开。
              </p>
            </div>
          ) : (
            <video
              key={item.id}
              ref={videoRef}
              src={videoSrc}
              controls
              autoPlay
              className="w-full max-h-[70vh] object-contain"
              onError={() => setHasError(true)}
            />
          )}
        </div>

        {/* 元信息 + 发布按钮 */}
        <div className="mt-3 flex items-center justify-between gap-3 px-1">
          <div className="flex items-center gap-2 text-xs text-slate-400 flex-wrap">
            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
              {item.source_label}
            </span>
            <span>
              时长{' '}
              {Math.floor(item.duration / 60)}:
              {Math.floor(item.duration % 60)
                .toString()
                .padStart(2, '0')}
            </span>
            {item.file_size > 0 && (
              <>
                <span>·</span>
                <span>
                  {item.file_size < 1024 * 1024
                    ? `${(item.file_size / 1024).toFixed(0)}KB`
                    : `${(item.file_size / 1024 / 1024).toFixed(1)}MB`}
                </span>
              </>
            )}
            <span>·</span>
            <span>{new Date(item.created_at).toLocaleString()}</span>
          </div>
          <button
            type="button"
            onClick={onPublish}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors shrink-0"
          >
            <Send className="w-3.5 h-3.5" />
            {isSelected ? '已选中，去右侧发布' : '选中并发布'}
          </button>
        </div>

        <p className="text-center text-xs text-slate-600 mt-2">
          点击遮罩或按 Esc 关闭
        </p>
      </div>
    </div>
  )
}
