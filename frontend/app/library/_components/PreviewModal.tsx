'use client'

import { X, AlertTriangle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Video } from '@/lib/store'
import { videosApi } from '@/lib/api'

interface PreviewModalProps {
  video: Video
  hasError: boolean
  onClose: () => void
  onError: () => void
}

export function PreviewModal({ video, hasError, onClose, onError }: PreviewModalProps) {
  const [highlightLoading, setHighlightLoading] = useState(false)
  const [highlights, setHighlights] = useState<Array<{
    clip_id: string
    start_time: number
    end_time: number
    duration: number
    highlight_score: number
    summary_text?: string | null
  }>>([])
  const [highlightError, setHighlightError] = useState('')
  const videoRef = useRef<HTMLVideoElement | null>(null)

  // Close on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // Fetch highlights for this video (best-effort，不阻塞主体验)
  useEffect(() => {
    let cancelled = false
    setHighlightLoading(true)
    setHighlightError('')
    videosApi
      .highlights(video.id, { limit: 20, min_score: 0.3 })
      .then((res) => {
        if (cancelled) return
        setHighlights(res.segments || [])
      })
      .catch(() => {
        if (cancelled) return
        setHighlightError('高光识别结果获取失败，可稍后在匹配工作区查看。')
      })
      .finally(() => {
        if (!cancelled) setHighlightLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [video.id])

  const handleJumpToHighlight = (startTime: number) => {
    // 在完整视频上按时间点跳转
    const el = videoRef.current
    if (!el) return
    try {
      el.currentTime = Math.max(0, startTime || 0)
      void el.play().catch(() => {})
    } catch {
      // ignore
    }
  }

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
              ref={videoRef}
              src={`/api/videos/${video.id}/stream`}
              controls
              autoPlay
              className="w-full max-h-[75vh] object-contain"
              onError={onError}
            />
          )}
        </div>

        {/* Highlights */}
        <div className="mt-4 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-slate-300">高光片段</p>
            {highlightLoading && (
              <span className="text-[10px] text-slate-500">分析中…</span>
            )}
          </div>
          {highlightError ? (
            <p className="text-[11px] text-slate-500">{highlightError}</p>
          ) : highlights.length === 0 ? (
            <p className="text-[11px] text-slate-500">
              暂无明显高光片段（可通过「匹配」页面结合文案进一步检索）。
            </p>
          ) : (
            <div className="max-h-40 overflow-y-auto styled-scrollbar rounded-lg border border-slate-800/80 bg-slate-900/60 divide-y divide-slate-800/80">
              {highlights.map((h) => (
                <button
                  key={h.clip_id}
                  type="button"
                  onClick={() => handleJumpToHighlight(h.start_time)}
                  className="w-full text-left px-3 py-2 text-[11px] text-slate-200 flex flex-col gap-0.5 hover:bg-slate-800/80 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">
                      {h.start_time.toFixed(1)}s – {h.end_time.toFixed(1)}s
                    </span>
                    <span className="text-[10px] text-amber-300">
                      高光分数 {h.highlight_score.toFixed(2)}
                    </span>
                  </div>
                  {h.summary_text && (
                    <p className="text-[11px] text-slate-300 line-clamp-2">{h.summary_text}</p>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* hint */}
        <p className="text-center text-xs text-slate-600 mt-2">点击遮罩或按 Esc 关闭</p>
      </div>
    </div>
  )
}
