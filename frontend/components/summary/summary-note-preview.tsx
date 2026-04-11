'use client'

import { useCallback, useMemo, useRef, type ComponentPropsWithoutRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL } from '@/lib/runtime-config'

/** 将 `mm:ss` 或 `h:mm:ss` 转为从片头起的秒数 */
export function timeTokenToSec(t: string): number {
  const parts = t
    .trim()
    .split(':')
    .map((x) => parseInt(x, 10))
  if (parts.some((n) => Number.isNaN(n))) return 0
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  return 0
}

/** 将笔记中的占位转为可点击的 video-time 链接（与后端提示一致） */
export function preprocessNoteMarkdown(md: string): string {
  let s = md
  s = s.replace(/\*Screenshot-\[(\d{1,2}:\d{2}(?::\d{2})?)\]/g, (_, t: string) => {
    const sec = timeTokenToSec(t)
    return `\n\n> **原片截图位** [${t} — 点我预览](video-time:${sec})\n\n`
  })
  s = s.replace(/\*Content-\[(\d{1,2}:\d{2}(?::\d{2})?)\]/g, (_, t: string) => {
    const sec = timeTokenToSec(t)
    return `[▶ ${t}](video-time:${sec})`
  })
  return s
}

const mdContainer =
  'text-slate-200 text-sm leading-relaxed [&_h1]:text-xl [&_h1]:font-semibold [&_h1]:mt-4 [&_h1]:mb-2 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2 [&_h3]:text-base [&_h3]:font-medium [&_h3]:mt-3 [&_p]:my-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-0.5 [&_blockquote]:border-l-2 [&_blockquote]:border-slate-600 [&_blockquote]:pl-3 [&_blockquote]:my-3 [&_blockquote]:text-slate-300 [&_code]:text-cyan-200 [&_code]:bg-slate-800/80 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-[13px] [&_pre]:bg-slate-900 [&_pre]:p-3 [&_pre]:rounded-lg [&_pre]:overflow-x-auto [&_a]:break-words'

type Props = {
  markdown: string
  videoId: string | null
  className?: string
}

export function SummaryNotePreview({ markdown, videoId, className = '' }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)

  const seek = useCallback((sec: number) => {
    const el = videoRef.current
    if (!el || !Number.isFinite(sec)) return
    el.currentTime = Math.max(0, sec)
    void el.play().catch(() => {})
  }, [])

  const processed = useMemo(() => preprocessNoteMarkdown(markdown), [markdown])

  const streamUrl = videoId
    ? `${(API_BASE_URL || '').replace(/\/$/, '')}/api/videos/${videoId}/stream`
    : ''

  const components = useMemo(
    () => ({
      a: ({ href, children, ...rest }: ComponentPropsWithoutRef<'a'>) => {
        if (href?.startsWith('video-time:')) {
          const sec = parseInt(href.replace('video-time:', ''), 10)
          return (
            <button
              type="button"
              className="inline text-cyan-400 hover:text-cyan-300 underline underline-offset-2 cursor-pointer bg-transparent border-0 p-0 font-inherit text-left"
              onClick={(e) => {
                e.preventDefault()
                seek(sec)
              }}
            >
              {children}
            </button>
          )
        }
        return (
          <a
            href={href}
            className="text-cyan-400/90 underline hover:text-cyan-300"
            target="_blank"
            rel="noreferrer"
            {...rest}
          >
            {children}
          </a>
        )
      },
    }),
    [seek],
  )

  return (
    <div className={className}>
      {streamUrl ? (
        <video
          ref={videoRef}
          src={streamUrl}
          controls
          className="w-full max-h-[min(280px,40vh)] rounded-lg border border-slate-800 bg-black object-contain"
          preload="metadata"
        />
      ) : (
        <div className="rounded-lg border border-dashed border-slate-700 bg-slate-950/50 p-6 text-center text-sm text-slate-500">
          选择素材视频后，此处可预览画面；笔记里带时间点的链接可点击跳转。
        </div>
      )}
      <div className={`mt-4 ${mdContainer}`}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {processed || '（暂无内容）'}
        </ReactMarkdown>
      </div>
    </div>
  )
}
